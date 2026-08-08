# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

from typing import Any

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, getdate

from erpnext.assets.doctype.asset_activity.asset_activity import add_asset_activity
from erpnext.assets.doctype.asset_depreciation_schedule.asset_depreciation_schedule import (
	get_asset_depr_schedule_doc,
)

from erpnext_extensions.asset_usage_depreciation.constants import (
	COMPANY_FIELD_REDUCED_HANDLING,
	HANDLING_EXTEND,
	HANDLING_REDISTRIBUTE,
)
from erpnext_extensions.asset_usage_depreciation.services.ads_replace import (
	build_replan_notes,
	recompute_accumulated,
	replace_asset_depr_schedule,
)
from erpnext_extensions.asset_usage_depreciation.services.locks import lock_ads, lock_asset
from erpnext_extensions.asset_usage_depreciation.services.mode_a import apply_mode_a_extension
from erpnext_extensions.asset_usage_depreciation.services.mode_b import redistribute_unposted_amounts
from erpnext_extensions.asset_usage_depreciation.services.usage_timeline import (
	day_weighted_factor,
	factor_on_date,
	load_submitted_usage_periods,
	validate_timeline_consistency,
)

# Recursion / re-entrancy guard (request-local via frappe.flags)
_FLAG_USAGE_REPLAN_IN_PROGRESS = "usage_replan_in_progress"


def asset_has_submitted_usage_periods(asset_name: str) -> bool:
	return bool(
		frappe.db.exists(
			"Asset Usage Period",
			{"asset": asset_name, "docstatus": 1},
		)
	)


def get_reduced_depreciation_handling(company: str) -> str:
	value = frappe.db.get_value("Company", company, COMPANY_FIELD_REDUCED_HANDLING)
	if value in (HANDLING_EXTEND, HANDLING_REDISTRIBUTE):
		return value
	return HANDLING_EXTEND


def replan_asset_usage_depreciation(asset_name: str, trigger_doc=None, context: dict | None = None):
	"""Single orchestration entry point for usage-driven ADS replanning."""
	if frappe.flags.get(_FLAG_USAGE_REPLAN_IN_PROGRESS):
		return

	context = context or {}
	if context.get("skip_if_no_usage") and not asset_has_submitted_usage_periods(asset_name):
		return

	# Always no-op when no submitted usage periods (except when called from Usage Period itself
	# which may be mid-cancel — still load timeline after state change).
	frappe.flags[_FLAG_USAGE_REPLAN_IN_PROGRESS] = True
	try:
		_replan_asset_usage_depreciation(asset_name, trigger_doc=trigger_doc, context=context)
	finally:
		frappe.flags[_FLAG_USAGE_REPLAN_IN_PROGRESS] = False


def _replan_asset_usage_depreciation(asset_name: str, trigger_doc=None, context: dict | None = None):
	lock_asset(asset_name)
	asset = frappe.get_doc("Asset", asset_name)

	if not asset.calculate_depreciation:
		return

	timeline = load_submitted_usage_periods(asset_name)
	if not timeline and not (trigger_doc and trigger_doc.doctype == "Asset Usage Period"):
		# No usage timeline ⇒ leave standard ERPNext schedule alone
		return

	if timeline:
		validate_timeline_consistency(timeline)

	policy = get_reduced_depreciation_handling(asset.company)
	precision = asset.precision("net_purchase_amount")

	# Discover Active ADS for each finance book row
	ads_jobs: list[tuple[Any, Any]] = []
	for fb in asset.get("finance_books") or []:
		ads = get_asset_depr_schedule_doc(asset.name, "Active", fb.finance_book)
		if not ads:
			continue
		ads_jobs.append((fb, ads))

	if not ads_jobs:
		frappe.throw(
			_("No Active Asset Depreciation Schedule found for Asset {0}.").format(asset_name)
		)

	# Preflight all ADS before mutating any
	for fb, ads in ads_jobs:
		_validate_supported_method(fb, ads)
		_validate_posted_prefix(ads)
		_validate_no_draft_depreciation_je(asset, ads)

	prepared: list[dict[str, Any]] = []

	for fb, ads in ads_jobs:
		lock_ads(ads.name)
		# Reload after lock
		ads = frappe.get_doc("Asset Depreciation Schedule", ads.name)
		_validate_posted_prefix(ads)
		_validate_no_draft_depreciation_je(asset, ads)

		posted_snapshot = _capture_posted_snapshot(ads)

		# Standard ERPNext rebuild of unposted tail
		temp = frappe.copy_doc(ads)
		temp.create_depreciation_schedule(fb)

		rows = _schedule_to_row_dicts(temp)
		_apply_usage_factors(rows, timeline, fb, asset, temp, precision)

		remaining = flt(fb.value_after_depreciation - fb.expected_value_after_useful_life, precision)
		suspended_message = None

		if not timeline:
			# Usage cancelled away: keep standard regenerated amounts (already in rows without factors)
			pass
		elif policy == HANDLING_REDISTRIBUTE:
			redistribute_unposted_amounts(rows, remaining, precision)
		else:
			base_installment = _estimate_base_installment(rows, precision)
			meta = apply_mode_a_extension(
				rows,
				remaining,
				timeline,
				frequency_of_depreciation=cint(fb.frequency_of_depreciation),
				base_installment=base_installment,
				precision=precision,
				resolve_factor_for_date=lambda d, _fb=fb, _asset=asset, _temp=temp: _factor_for_extension_date(
					timeline, d, _fb, _asset, _temp
				),
				daily_prorata_based=cint(fb.daily_prorata_based),
			)
			suspended_message = meta.get("message")

		_enforce_salvage(rows, remaining, precision, allow_incomplete=bool(suspended_message))
		recompute_accumulated(rows, flt(asset.opening_accumulated_depreciation), precision)
		_assert_posted_unchanged(posted_snapshot, rows, precision)

		notes = build_replan_notes(asset.name, trigger_doc, suspended_message)
		row_diffs = _build_row_diffs(ads, rows, precision)

		prepared.append(
			{
				"ads": ads,
				"fb": fb,
				"rows": rows,
				"notes": notes,
				"row_diffs": row_diffs,
				"suspended_message": suspended_message,
			}
		)

	# Replace all ADS atomically (same DB transaction; throw rolls back)
	for item in prepared:
		new_ads = replace_asset_depr_schedule(item["ads"], item["rows"], item["notes"])
		_write_audit(asset, trigger_doc, item["ads"].name, new_ads.name, item["fb"], item["row_diffs"])
		if item.get("suspended_message"):
			add_asset_activity(asset.name, item["suspended_message"])


def _validate_supported_method(fb, ads) -> None:
	method = fb.depreciation_method or ads.depreciation_method
	shift_based = cint(fb.shift_based or ads.shift_based)
	if method != "Straight Line" or shift_based:
		frappe.throw(
			_(
				"Asset Usage Depreciation supports only Straight Line schedules without shift-based "
				"depreciation. Finance Book '{0}' uses method '{1}' (shift_based={2}). "
				"The entire usage replan was aborted."
			).format(fb.finance_book or _("(default)"), method, shift_based)
		)


def _validate_posted_prefix(ads) -> None:
	seen_unposted = False
	for row in ads.get("depreciation_schedule") or []:
		if row.journal_entry:
			if seen_unposted:
				frappe.throw(
					_(
						"Asset Depreciation Schedule {0} has a non-contiguous posted state "
						"(a submitted Journal Entry appears after an unposted row). "
						"Usage replan aborted. Do not auto-repair; resolve the schedule manually."
					).format(ads.name)
				)
			# Must be submitted JE
			je_status = frappe.db.get_value("Journal Entry", row.journal_entry, "docstatus")
			if je_status != 1:
				frappe.throw(
					_(
						"Depreciation Schedule row on {0} links Journal Entry {1} which is not submitted "
						"(docstatus={2}). Submit or cancel it before replanning."
					).format(row.schedule_date, row.journal_entry, je_status)
				)
		else:
			seen_unposted = True


def _validate_no_draft_depreciation_je(asset, ads) -> None:
	# Linked draft on schedule rows
	for row in ads.get("depreciation_schedule") or []:
		if not row.journal_entry:
			continue
		je_status = frappe.db.get_value("Journal Entry", row.journal_entry, "docstatus")
		if je_status == 0:
			frappe.throw(
				_(
					"Draft Depreciation Entry {0} is linked to the schedule. "
					"Submit or cancel it before usage-based replanning."
				).format(row.journal_entry)
			)

	# Unlinked draft Depreciation Entry referencing the asset
	drafts = frappe.db.sql(
		"""
		SELECT DISTINCT je.name
		FROM `tabJournal Entry` je
		INNER JOIN `tabJournal Entry Account` jea ON jea.parent = je.name
		WHERE je.docstatus = 0
			AND je.voucher_type = 'Depreciation Entry'
			AND jea.reference_type = 'Asset'
			AND jea.reference_name = %s
		LIMIT 1
		""",
		asset.name,
	)
	if drafts:
		frappe.throw(
			_(
				"Draft Depreciation Entry {0} references Asset {1}. "
				"Submit or cancel it before usage-based replanning."
			).format(drafts[0][0], asset.name)
		)


def _capture_posted_snapshot(ads) -> list[dict[str, Any]]:
	snapshot = []
	for row in ads.get("depreciation_schedule") or []:
		if not row.journal_entry:
			break
		snapshot.append(
			{
				"schedule_date": getdate(row.schedule_date),
				"depreciation_amount": flt(row.depreciation_amount),
				"accumulated_depreciation_amount": flt(row.accumulated_depreciation_amount),
				"journal_entry": row.journal_entry,
				"shift": row.shift,
			}
		)
	return snapshot


def _schedule_to_row_dicts(ads) -> list[dict[str, Any]]:
	rows = []
	for row in ads.get("depreciation_schedule") or []:
		rows.append(
			{
				"schedule_date": getdate(row.schedule_date),
				"depreciation_amount": flt(row.depreciation_amount),
				"accumulated_depreciation_amount": flt(row.accumulated_depreciation_amount),
				"journal_entry": row.journal_entry,
				"shift": row.shift,
				"usage_factor": 1.0,
			}
		)
	return rows


def _coverage_window(ads_or_temp, row_idx: int, fb, asset) -> tuple:
	"""Return inclusive [start, end] coverage for schedule row at index."""
	schedule = ads_or_temp.get("depreciation_schedule") or []
	end = getdate(schedule[row_idx].schedule_date if hasattr(schedule[row_idx], "schedule_date") else schedule[row_idx]["schedule_date"])
	if row_idx > 0:
		prev = schedule[row_idx - 1]
		prev_date = getdate(prev.schedule_date if hasattr(prev, "schedule_date") else prev["schedule_date"])
		start = add_days(prev_date, 1)
	else:
		# Align with ERPNext daily window helper when possible
		if cint(fb.daily_prorata_based):
			from erpnext.assets.doctype.asset_depreciation_schedule.deppreciation_schedule_controller import (
				DepreciationScheduleController,
			)

			# Use controller helper via temp if available
			if hasattr(ads_or_temp, "_get_total_days"):
				start, _days = ads_or_temp._get_total_days(fb.depreciation_start_date, row_idx)
				return getdate(start), end
		start = getdate(asset.available_for_use_date)
	return start, end


def _apply_usage_factors(rows, timeline, fb, asset, temp, precision) -> None:
	if not timeline:
		return

	for idx, row in enumerate(rows):
		if row.get("journal_entry"):
			continue
		standard = flt(row["depreciation_amount"], precision)
		if cint(fb.daily_prorata_based):
			start, end = _coverage_window_from_rows(rows, idx, fb, asset, temp)
			factor = day_weighted_factor(timeline, start, end)
		else:
			factor = factor_on_date(timeline, row["schedule_date"])
		row["usage_factor"] = factor
		row["depreciation_amount"] = flt(standard * factor, precision)


def _coverage_window_from_rows(rows, idx, fb, asset, temp) -> tuple:
	end = getdate(rows[idx]["schedule_date"])
	if idx > 0:
		start = add_days(getdate(rows[idx - 1]["schedule_date"]), 1)
		return start, end
	# First row: use ERPNext _get_total_days when possible
	if hasattr(temp, "_get_total_days"):
		try:
			start, _days = temp._get_total_days(fb.depreciation_start_date, idx)
			return getdate(start), end
		except Exception:
			pass
	return getdate(asset.available_for_use_date), end


def _factor_for_extension_date(timeline, on_date, fb, asset, temp) -> float:
	# Extensions use schedule-date factor (non-daily) or same factor_on_date for daily
	# Day-weighted needs a window; for appended monthly rows use factor_on_date
	return factor_on_date(timeline, on_date)


def _estimate_base_installment(rows, precision) -> float:
	"""Prefer a Normal (factor~1) unposted standard-equivalent installment."""
	candidates = []
	for row in rows:
		if row.get("journal_entry"):
			continue
		factor = flt(row.get("usage_factor") or 1)
		amt = flt(row.get("depreciation_amount"))
		if factor > 0 and amt > 0:
			candidates.append(flt(amt / factor, precision))
	if candidates:
		# Use the first (earliest) standard installment
		return candidates[0]
	return 0.0


def _enforce_salvage(rows, remaining, precision, allow_incomplete: bool = False) -> None:
	unposted = [r for r in rows if not r.get("journal_entry")]
	total = flt(sum(flt(r["depreciation_amount"]) for r in unposted), precision)
	target = flt(remaining, precision)

	if allow_incomplete:
		if total - target > 1.0 / (10**precision):
			frappe.throw(
				_("Usage replan would depreciate below salvage value (unposted {0} > remaining {1}).").format(
					total, target
				)
			)
		return

	diff = flt(target - total, precision)
	if not unposted:
		if abs(diff) > 0:
			frappe.throw(_("No unposted rows available to allocate remaining depreciable value {0}.").format(diff))
		return

	# Adjust last unposted row to hit salvage exactly
	unposted[-1]["depreciation_amount"] = flt(unposted[-1]["depreciation_amount"] + diff, precision)
	if unposted[-1]["depreciation_amount"] < 0:
		frappe.throw(_("Salvage enforcement produced a negative depreciation amount."))


def _assert_posted_unchanged(snapshot, rows, precision) -> None:
	posted_rows = [r for r in rows if r.get("journal_entry")]
	if len(posted_rows) < len(snapshot):
		frappe.throw(_("Usage replan dropped posted depreciation rows. Aborted."))
	for i, expected in enumerate(snapshot):
		actual = posted_rows[i]
		if getdate(actual["schedule_date"]) != expected["schedule_date"]:
			frappe.throw(_("Posted schedule_date changed during usage replan. Aborted."))
		if flt(actual["depreciation_amount"], precision) != flt(expected["depreciation_amount"], precision):
			frappe.throw(_("Posted depreciation_amount changed during usage replan. Aborted."))
		if actual.get("journal_entry") != expected["journal_entry"]:
			frappe.throw(_("Posted journal_entry link changed during usage replan. Aborted."))


def _build_row_diffs(old_ads, new_rows, precision) -> list[dict[str, Any]]:
	old_map = {}
	for row in old_ads.get("depreciation_schedule") or []:
		if row.journal_entry:
			continue
		old_map[getdate(row.schedule_date)] = flt(row.depreciation_amount, precision)

	diffs = []
	for row in new_rows:
		if row.get("journal_entry"):
			continue
		d = getdate(row["schedule_date"])
		old_amt = old_map.get(d)
		new_amt = flt(row["depreciation_amount"], precision)
		if old_amt is None or flt(old_amt, precision) != new_amt:
			diffs.append({"schedule_date": d, "old_amount": old_amt, "new_amount": new_amt})
	return diffs


def _write_audit(asset, trigger_doc, old_ads_name, new_ads_name, fb, row_diffs) -> None:
	add_asset_activity(
		asset.name,
		_("Depreciation schedule replanned ({0} → {1}) due to Asset Usage Depreciation.").format(
			old_ads_name, new_ads_name
		),
	)

	if not trigger_doc or trigger_doc.doctype != "Asset Usage Period":
		return

	if trigger_doc.docstatus != 1:
		return

	# Insert child rows directly to avoid TimestampMismatch on the parent
	# document mid on_submit / before cancel.
	parent = trigger_doc.name
	idx = cint(frappe.db.sql(
		"SELECT COALESCE(MAX(idx), 0) FROM `tabAsset Usage Replan Log` WHERE parent=%s",
		parent,
	)[0][0])

	for diff in row_diffs:
		idx += 1
		frappe.get_doc(
			{
				"doctype": "Asset Usage Replan Log",
				"parent": parent,
				"parenttype": "Asset Usage Period",
				"parentfield": "replan_log",
				"idx": idx,
				"old_ads": old_ads_name,
				"new_ads": new_ads_name,
				"schedule_date": diff["schedule_date"],
				"old_amount": diff["old_amount"],
				"new_amount": diff["new_amount"],
				"finance_book": fb.finance_book,
			}
		).db_insert()

