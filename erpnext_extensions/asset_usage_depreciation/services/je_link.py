# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

"""Repair Depreciation Entry → ADS row linking when core date comparison fails.

ERPNext 16.30.0 ``JournalEntry.update_journal_entry_link_on_depr_schedule``
compares ``schedule_date == posting_date`` without ``getdate()``. When
``posting_date`` remains a string (common after programmatic JE create/submit),
the link is silently skipped even though NBV is still updated.

This hook only sets the missing ``journal_entry`` link using ``getdate()``
equality. It does not change amounts, cancel JEs, or replan schedules.
"""

from __future__ import annotations

import frappe
from frappe.utils import flt, getdate

from erpnext.assets.doctype.asset_depreciation_schedule.asset_depreciation_schedule import (
	get_depr_schedule,
)


def ensure_depreciation_schedule_je_link(doc, method=None):
	"""Journal Entry on_submit: ensure ADS row is linked for Depreciation Entry."""
	if getattr(doc, "voucher_type", None) != "Depreciation Entry":
		return
	if frappe.flags.get("usage_replan_in_progress"):
		return

	for je_row in doc.get("accounts") or []:
		if not (
			je_row.reference_type == "Asset"
			and je_row.reference_name
			and flt(je_row.debit)
			and frappe.get_cached_value("Account", je_row.account, "root_type") == "Expense"
		):
			continue

		if not frappe.db.get_value("Asset", je_row.reference_name, "calculate_depreciation"):
			continue

		depr_schedule = get_depr_schedule(je_row.reference_name, "Active", doc.finance_book)
		precision = je_row.precision("debit")
		posting = getdate(doc.posting_date)

		for schedule_row in depr_schedule or []:
			if schedule_row.journal_entry:
				if schedule_row.journal_entry == doc.name:
					return
				continue
			if getdate(schedule_row.schedule_date) != posting:
				continue
			if flt(schedule_row.depreciation_amount, precision) != flt(je_row.debit, precision):
				continue
			frappe.db.set_value("Depreciation Schedule", schedule_row.name, "journal_entry", doc.name)
			return
