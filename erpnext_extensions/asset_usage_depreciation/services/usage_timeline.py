# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

from typing import Any

import frappe
from frappe import _
from frappe.utils import date_diff, flt, getdate

from erpnext_extensions.asset_usage_depreciation.constants import (
	MODE_NO_DEPRECIATION,
	MODE_NORMAL,
	MODE_PERCENTAGE,
)


def mode_to_factor(mode: str, percentage: float | None = None) -> float:
	"""Return effective usage factor for a mode."""
	if mode == MODE_NORMAL:
		return 1.0
	if mode == MODE_NO_DEPRECIATION:
		return 0.0
	if mode == MODE_PERCENTAGE:
		pct = flt(percentage)
		if pct <= 0 or pct >= 100:
			frappe.throw(
				_("Percentage mode requires a value greater than 0 and less than 100. Got {0}.").format(pct)
			)
		return pct / 100.0
	frappe.throw(_("Unknown depreciation mode: {0}").format(mode))


def load_submitted_usage_periods(asset_name: str, exclude: str | None = None) -> list[dict[str, Any]]:
	"""Load submitted (docstatus=1) usage periods for an asset, sorted by from_date."""
	filters: dict[str, Any] = {"asset": asset_name, "docstatus": 1}
	if exclude:
		filters["name"] = ["!=", exclude]

	rows = frappe.get_all(
		"Asset Usage Period",
		filters=filters,
		fields=[
			"name",
			"from_date",
			"to_date",
			"depreciation_mode",
			"depreciation_percentage",
		],
		order_by="from_date asc, creation asc",
	)
	for row in rows:
		row["factor"] = mode_to_factor(row.depreciation_mode, row.depreciation_percentage)
		row["from_date"] = getdate(row.from_date)
		row["to_date"] = getdate(row.to_date) if row.to_date else None
	return rows


def validate_timeline_consistency(periods: list[dict[str, Any]]) -> None:
	"""Validate non-overlap and single latest open-ended period."""
	open_ended = [p for p in periods if not p.get("to_date")]
	if len(open_ended) > 1:
		frappe.throw(_("Only one open-ended Asset Usage Period is allowed per Asset."))

	if open_ended:
		latest = max(periods, key=lambda p: p["from_date"])
		if open_ended[0]["name"] != latest["name"] and open_ended[0]["from_date"] != latest["from_date"]:
			frappe.throw(_("An open-ended Asset Usage Period must be the latest period for the Asset."))
		# If same from_date edge case, still require open-ended to be last in sorted order
		if periods and periods[-1]["name"] != open_ended[0]["name"]:
			frappe.throw(_("An open-ended Asset Usage Period must be the latest period for the Asset."))

	for i, left in enumerate(periods):
		left_from = left["from_date"]
		left_to = left["to_date"]
		if left_to and left_from > left_to:
			frappe.throw(
				_("Asset Usage Period {0}: From Date must be on or before To Date.").format(left["name"])
			)
		for right in periods[i + 1 :]:
			right_from = right["from_date"]
			right_to = right["to_date"]
			if _ranges_overlap(left_from, left_to, right_from, right_to):
				frappe.throw(
					_(
						"Asset Usage Periods {0} and {1} overlap. Periods for the same Asset must not overlap."
					).format(left["name"], right["name"])
				)


def _ranges_overlap(a_from, a_to, b_from, b_to) -> bool:
	"""Inclusive date ranges; None to_date means open-ended (+inf)."""
	a_end = a_to or getdate("9999-12-31")
	b_end = b_to or getdate("9999-12-31")
	return a_from <= b_end and b_from <= a_end


def factor_on_date(periods: list[dict[str, Any]], on_date) -> float:
	"""Resolve usage factor for a single date. Gaps => Normal (1.0)."""
	on_date = getdate(on_date)
	for period in periods:
		start = period["from_date"]
		end = period["to_date"]
		if on_date < start:
			continue
		if end is None or on_date <= end:
			return flt(period["factor"])
	return 1.0


def day_weighted_factor(periods: list[dict[str, Any]], start_date, end_date) -> float:
	"""Exact calendar-day weighted average factor over [start_date, end_date] inclusive."""
	start_date = getdate(start_date)
	end_date = getdate(end_date)
	if end_date < start_date:
		frappe.throw(_("day_weighted_factor: end_date must be on or after start_date"))

	total_days = date_diff(end_date, start_date) + 1
	if total_days <= 0:
		return 1.0

	weighted = 0.0
	cursor = start_date
	# Walk day by day in segments for efficiency using period boundaries
	# Simple O(days) is fine for monthly windows; keep deterministic.
	from frappe.utils import add_days

	for offset in range(total_days):
		day = add_days(start_date, offset)
		weighted += factor_on_date(periods, day)

	return flt(weighted / total_days)


def has_future_positive_factor(periods: list[dict[str, Any]], from_date) -> bool:
	"""True if any day on/after from_date can have factor > 0 given the timeline.

	Gaps are Normal (1.0). An open-ended No Depreciation covering from_date
	with no later positive period means no future positive factor.
	"""
	from_date = getdate(from_date)

	for period in periods:
		if flt(period["factor"]) <= 0:
			continue
		end = period["to_date"]
		if end is not None and end < from_date:
			continue
		return True

	# No explicit positive period intersects the future.
	# Open-ended zero covering from_date => suspended forever.
	for period in periods:
		if period["from_date"] <= from_date and period["to_date"] is None and flt(period["factor"]) <= 0:
			return False

	# Empty timeline, gaps, or closed zero periods that eventually end => Normal gap possible.
	return True
