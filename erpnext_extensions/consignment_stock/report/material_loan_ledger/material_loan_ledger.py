# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt

from erpnext_extensions.consignment_stock.material_loan.constants import (
	F_IS_LOAN_ISSUE,
	F_IS_LOAN_RETURN,
	F_ISSUE_RATE,
	F_ISSUE_SE,
	F_PARTY,
	F_PARTY_TYPE,
)


def execute(filters=None):
	filters = filters or {}
	columns = [
		{"label": _("Date"), "fieldname": "posting_date", "fieldtype": "Date", "width": 100},
		{"label": _("Party"), "fieldname": "party", "fieldtype": "Data", "width": 140},
		{"label": _("Item"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 120},
		{"label": _("Issue"), "fieldname": "issue", "fieldtype": "Link", "options": "Stock Entry", "width": 130},
		{"label": _("Return"), "fieldname": "return_se", "fieldtype": "Link", "options": "Stock Entry", "width": 130},
		{"label": _("Issued Qty"), "fieldname": "issued_qty", "fieldtype": "Float", "width": 100},
		{"label": _("Returned Qty"), "fieldname": "returned_qty", "fieldtype": "Float", "width": 100},
		{"label": _("Balance Qty"), "fieldname": "balance_qty", "fieldtype": "Float", "width": 100},
		{"label": _("Debit Value"), "fieldname": "debit_value", "fieldtype": "Currency", "width": 110},
		{"label": _("Credit Value"), "fieldname": "credit_value", "fieldtype": "Currency", "width": 110},
		{"label": _("Balance Value"), "fieldname": "balance_value", "fieldtype": "Currency", "width": 110},
	]

	conds = ["se.docstatus=1"]
	values = {}
	if filters.get("company"):
		conds.append("se.company=%(company)s")
		values["company"] = filters["company"]
	if filters.get("party"):
		conds.append(f"se.{F_PARTY}=%(party)s")
		values["party"] = filters["party"]

	issue_rows = frappe.db.sql(
		f"""
		select se.posting_date, se.{F_PARTY} as party, sed.item_code, se.name as issue,
			null as return_se, coalesce(sed.transfer_qty, sed.qty) as issued_qty,
			0 as returned_qty, sed.{F_ISSUE_RATE} as rate
		from `tabStock Entry` se
		inner join `tabStock Entry Detail` sed on sed.parent=se.name
		where se.{F_IS_LOAN_ISSUE}=1 and {' and '.join(conds)}
		""",
		values,
		as_dict=True,
	)
	return_rows = frappe.db.sql(
		f"""
		select se.posting_date, se.{F_PARTY} as party, sed.item_code,
			sed.{F_ISSUE_SE} as issue, se.name as return_se,
			0 as issued_qty, coalesce(sed.transfer_qty, sed.qty) as returned_qty,
			sed.{F_ISSUE_RATE} as rate
		from `tabStock Entry` se
		inner join `tabStock Entry Detail` sed on sed.parent=se.name
		where se.{F_IS_LOAN_RETURN}=1 and {' and '.join(conds)}
		""",
		values,
		as_dict=True,
	)

	entries = sorted(list(issue_rows) + list(return_rows), key=lambda r: (r.posting_date, r.issue or ""))
	bal_qty = 0.0
	bal_val = 0.0
	data = []
	for r in entries:
		issued = flt(r.issued_qty)
		returned = flt(r.returned_qty)
		rate = flt(r.rate)
		debit = issued * rate
		credit = returned * rate
		bal_qty += issued - returned
		bal_val += debit - credit
		data.append(
			{
				"posting_date": r.posting_date,
				"party": r.party,
				"item_code": r.item_code,
				"issue": r.issue,
				"return_se": r.return_se,
				"issued_qty": issued,
				"returned_qty": returned,
				"balance_qty": bal_qty,
				"debit_value": debit,
				"credit_value": credit,
				"balance_value": bal_val,
			}
		)
	return columns, data
