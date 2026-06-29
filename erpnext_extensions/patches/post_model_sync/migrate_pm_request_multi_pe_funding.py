"""Backfill PM Request multi-PE funding fields and recompute aggregates."""

from __future__ import annotations

import frappe
from frappe.utils import cint, flt

from erpnext_extensions.petty_management.services.funding_queries import (
	resolve_latest_payment_entry,
	sum_submitted_pe_amount,
)
from erpnext_extensions.petty_management.services.funding_service import sync_pm_request_funding_fields


def execute():
	frappe.reload_doc("petty_management", "doctype", "pm_request")
	meta = frappe.get_meta("PM Request")
	if not meta.has_field("total_paid_amount"):
		return

	for name in frappe.get_all("PM Request", pluck="name"):
		row = frappe.db.get_value(
			"PM Request",
			name,
			["payment_status", "payment_entry"],
			as_dict=True,
		)
		ps = (row.payment_status or "").strip()
		if ps == "Paid" and meta.has_field("payment_status"):
			pass
		if ps not in ("Not Paid", "Partially Paid", "Paid") and meta.has_field("payment_status"):
			# Legacy single-value enum
			submitted = sum_submitted_pe_amount(name)
			requested = flt(frappe.db.get_value("PM Request", name, "total_requested_amount"))
			if submitted <= 1e-6:
				frappe.db.set_value("PM Request", name, "payment_status", "Not Paid", update_modified=False)
			elif submitted + 1e-6 < requested:
				frappe.db.set_value("PM Request", name, "payment_status", "Partially Paid", update_modified=False)
			else:
				frappe.db.set_value("PM Request", name, "payment_status", "Paid", update_modified=False)

		if cint(frappe.db.get_value("PM Request", name, "is_closed")) is None:
			frappe.db.set_value("PM Request", name, "is_closed", 0, update_modified=False)

		latest = resolve_latest_payment_entry(name)
		if latest and latest != row.payment_entry:
			frappe.db.set_value("PM Request", name, "payment_entry", latest, update_modified=False)

		try:
			sync_pm_request_funding_fields(name)
		except Exception:
			frappe.log_error(title="PM Request funding sync failed", message=name)

	frappe.db.commit()
