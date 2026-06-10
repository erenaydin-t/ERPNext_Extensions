# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt, getdate

from erpnext_extensions.facility_management.facility_balances import get_facility_balance_row


def execute(filters=None):
	filters = frappe._dict(filters or {})
	if not filters.get("company"):
		frappe.throw(_("Company is required"))
	if not filters.get("facility"):
		frappe.throw(_("Facility is required"))
	columns = get_columns()
	data = get_ledger_rows(filters)
	return columns, data


def get_columns():
	return [
		{"label": _("Date"), "fieldname": "posting_date", "fieldtype": "Date", "width": 100},
		{"label": _("Entry Type"), "fieldname": "entry_type", "fieldtype": "Data", "width": 140},
		{"label": _("Reference"), "fieldname": "reference", "fieldtype": "Dynamic Link", "options": "reference_doctype", "width": 140},
		{"label": _("Reference DocType"), "fieldname": "reference_doctype", "fieldtype": "Data", "hidden": 1},
		{"label": _("Principal Paid"), "fieldname": "principal_paid", "fieldtype": "Currency", "width": 120},
		{"label": _("Profit Paid"), "fieldname": "profit_paid", "fieldtype": "Currency", "width": 110},
		{"label": _("Penalty Paid"), "fieldname": "penalty_paid", "fieldtype": "Currency", "width": 110},
		{"label": _("Remaining Principal"), "fieldname": "remaining_principal", "fieldtype": "Currency", "width": 130},
		{"label": _("Remaining Profit"), "fieldname": "remaining_profit", "fieldtype": "Currency", "width": 120},
		{"label": _("Remarks"), "fieldname": "remarks", "fieldtype": "Data", "width": 200},
	]


def get_ledger_rows(filters):
	facility = filters.facility
	fac = frappe.get_doc("Facility", facility)
	if fac.company != filters.company:
		frappe.throw(_("Facility does not belong to the selected company."))
	from_date = getdate(filters.get("from_date") or fac.contract_date or "2000-01-01")
	to_date = getdate(filters.get("to_date") or frappe.utils.today())

	data = []
	running_p = flt(fac.principal_amount)
	running_pr = flt(fac.profit_amount)

	show_opening = frappe.utils.cint(fac.is_opening_facility) or flt(fac.opening_paid_principal_amount) or flt(
		fac.opening_paid_profit_amount
	) or flt(fac.opening_paid_penalty_amount)
	opening_date = getdate(fac.contract_date or fac.receive_date or from_date)
	if show_opening and opening_date <= to_date and opening_date >= from_date:
		op = flt(fac.opening_paid_principal_amount)
		opf = flt(fac.opening_paid_profit_amount)
		opp = flt(fac.opening_paid_penalty_amount)
		running_p -= op
		running_pr -= opf
		data.append(
			{
				"posting_date": opening_date,
				"entry_type": _("Opening Balance"),
				"reference_doctype": "",
				"reference": "",
				"principal_paid": op,
				"profit_paid": opf,
				"penalty_paid": opp,
				"remaining_principal": running_p,
				"remaining_profit": running_pr,
				"remarks": _("Opening / migrated paid amounts"),
			}
		)

	repayments = frappe.get_all(
		"Facility Repayment",
		filters={
			"facility": facility,
			"docstatus": 1,
			"posting_date": ["between", [from_date, to_date]],
		},
		fields=["name", "posting_date", "principal_amount", "profit_amount", "penalty_amount", "remarks"],
		order_by="posting_date asc, creation asc",
	)
	for rep in repayments:
		pp = flt(rep.principal_amount)
		pf = flt(rep.profit_amount)
		pn = flt(rep.penalty_amount)
		running_p -= pp
		running_pr -= pf
		data.append(
			{
				"posting_date": rep.posting_date,
				"entry_type": _("Facility Repayment"),
				"reference_doctype": "Facility Repayment",
				"reference": rep.name,
				"principal_paid": pp,
				"profit_paid": pf,
				"penalty_paid": pn,
				"remaining_principal": running_p,
				"remaining_profit": running_pr,
				"remarks": rep.remarks or "",
			}
		)
	return data
