# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

import frappe
from frappe.utils import cint, flt

from erpnext_extensions.petty_management.services.funding_queries import (
	count_linked_payment_entries,
	list_payment_entries_for_pm_request,
)
from erpnext_extensions.petty_management.services.request_api_guard import pm_request_names_for_report


def execute(filters=None):
	filters = filters or {}
	columns = [
		{"label": "PM Request", "fieldname": "pm_request", "fieldtype": "Link", "options": "PM Request", "width": 160},
		{"label": "Requested", "fieldname": "requested", "fieldtype": "Currency", "width": 110},
		{"label": "Paid", "fieldname": "paid", "fieldtype": "Currency", "width": 110},
		{"label": "Remaining", "fieldname": "remaining", "fieldtype": "Currency", "width": 110},
		{"label": "Allocated", "fieldname": "allocated", "fieldtype": "Currency", "width": 110},
		{"label": "Available", "fieldname": "available", "fieldtype": "Currency", "width": 110},
		{"label": "Payment Status", "fieldname": "payment_status", "fieldtype": "Data", "width": 120},
		{"label": "Closed", "fieldname": "is_closed", "fieldtype": "Check", "width": 70},
		{"label": "Latest PE", "fieldname": "latest_pe", "fieldtype": "Link", "options": "Payment Entry", "width": 140},
		{"label": "PE Count", "fieldname": "pe_count", "fieldtype": "Int", "width": 80},
		{"label": "Payment Entry", "fieldname": "payment_entry", "fieldtype": "Link", "options": "Payment Entry", "width": 140},
		{"label": "PE Amount", "fieldname": "pe_amount", "fieldtype": "Currency", "width": 110},
		{"label": "PE Status", "fieldname": "pe_status", "fieldtype": "Data", "width": 100},
	]

	data = []
	for pr in pm_request_names_for_report(filters):
		row = frappe.db.get_value(
			"PM Request",
			pr,
			[
				"total_requested_amount",
				"total_paid_amount",
				"remaining_to_pay",
				"allocated_amount",
				"available_for_clearance",
				"payment_status",
				"is_closed",
				"payment_entry",
			],
			as_dict=True,
		)
		if not row:
			continue
		pe_count = count_linked_payment_entries(pr, docstatus=(0, 1, 2))
		summary = {
			"pm_request": pr,
			"requested": flt(row.total_requested_amount),
			"paid": flt(row.total_paid_amount),
			"remaining": flt(row.remaining_to_pay),
			"allocated": flt(row.allocated_amount),
			"available": flt(row.available_for_clearance),
			"payment_status": row.payment_status,
			"is_closed": cint(row.is_closed),
			"latest_pe": row.payment_entry,
			"pe_count": pe_count,
			"indent": 0,
		}
		data.append(summary)
		for pe in list_payment_entries_for_pm_request(pr):
			data.append(
				{
					"pm_request": pr,
					"payment_entry": pe["payment_entry"],
					"pe_amount": flt(pe.get("amount")),
					"pe_status": pe.get("status") or "",
					"indent": 1,
				}
			)

	return columns, data
