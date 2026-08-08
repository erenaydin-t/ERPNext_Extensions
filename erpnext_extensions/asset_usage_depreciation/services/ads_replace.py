# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

from typing import Any

import frappe
from frappe import _
from frappe.utils import flt, get_link_to_form


def replace_asset_depr_schedule(
	old_ads,
	new_rows: list[dict[str, Any]],
	notes: str,
):
	"""Cancel Active ADS without cancelling posted JEs; submit replacement with new rows."""
	new_ads = frappe.copy_doc(old_ads)
	new_ads.depreciation_schedule = []
	new_ads.amended_from = None
	new_ads.status = "Draft"

	for row in new_rows:
		new_ads.append(
			"depreciation_schedule",
			{
				"schedule_date": row["schedule_date"],
				"depreciation_amount": row["depreciation_amount"],
				"accumulated_depreciation_amount": row.get("accumulated_depreciation_amount") or 0,
				"journal_entry": row.get("journal_entry"),
				"shift": row.get("shift"),
			},
		)

	new_ads.notes = notes

	old_ads.flags.should_not_cancel_depreciation_entries = True
	old_ads.cancel()

	new_ads.submit()
	return new_ads


def build_replan_notes(asset_name: str, trigger_doc=None, suspended_message: str | None = None) -> str:
	parts = [
		_("This schedule was replanned for Asset {0} by Asset Usage Depreciation.").format(
			get_link_to_form("Asset", asset_name)
		)
	]
	if trigger_doc:
		parts.append(
			_("Trigger: {0} {1}.").format(
				trigger_doc.doctype,
				get_link_to_form(trigger_doc.doctype, trigger_doc.name),
			)
		)
	if suspended_message:
		parts.append(str(suspended_message))
	return " ".join(parts)


def recompute_accumulated(rows: list[dict[str, Any]], opening_accumulated: float, precision: int) -> None:
	accum = flt(opening_accumulated, precision)
	for row in rows:
		if row.get("journal_entry") and row.get("accumulated_depreciation_amount") is not None:
			# Preserve posted accumulated; continue from it
			accum = flt(row["accumulated_depreciation_amount"], precision)
			continue
		accum = flt(accum + flt(row["depreciation_amount"]), precision)
		row["accumulated_depreciation_amount"] = accum
