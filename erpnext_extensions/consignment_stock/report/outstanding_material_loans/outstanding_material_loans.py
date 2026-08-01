# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt

from erpnext_extensions.consignment_stock.material_loan.constants import (
	F_EXPECTED_RETURN_DATE,
	F_IS_LOAN_ISSUE,
	F_ISSUE_RATE,
	F_PARTY,
	F_PARTY_TYPE,
	F_PHYSICAL_STATUS,
	F_RECOGNITION_STATUS,
	F_SETTLEMENT_STATUS,
)
from erpnext_extensions.consignment_stock.material_loan.returnable_qty import get_returned_qty


def execute(filters=None):
	filters = filters or {}
	columns = [
		{"label": _("Company"), "fieldname": "company", "fieldtype": "Link", "options": "Company", "width": 120},
		{"label": _("Party Type"), "fieldname": "party_type", "fieldtype": "Data", "width": 100},
		{"label": _("Party"), "fieldname": "party", "fieldtype": "Dynamic Link", "options": "party_type", "width": 140},
		{"label": _("Issue"), "fieldname": "issue", "fieldtype": "Link", "options": "Stock Entry", "width": 140},
		{"label": _("Issue Date"), "fieldname": "issue_date", "fieldtype": "Date", "width": 100},
		{"label": _("Expected Return Date"), "fieldname": "expected_return_date", "fieldtype": "Date", "width": 120},
		{"label": _("Item"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 120},
		{"label": _("Batch"), "fieldname": "batch_no", "fieldtype": "Link", "options": "Batch", "width": 100},
		{"label": _("Issued Qty"), "fieldname": "issued_qty", "fieldtype": "Float", "width": 100},
		{"label": _("Returned Qty"), "fieldname": "returned_qty", "fieldtype": "Float", "width": 100},
		{"label": _("Outstanding Qty"), "fieldname": "outstanding_qty", "fieldtype": "Float", "width": 110},
		{"label": _("Frozen Rate"), "fieldname": "frozen_rate", "fieldtype": "Currency", "width": 110},
		{"label": _("Outstanding Value"), "fieldname": "outstanding_value", "fieldtype": "Currency", "width": 120},
		{"label": _("Physical Status"), "fieldname": "physical_status", "fieldtype": "Data", "width": 120},
		{"label": _("Recognition Status"), "fieldname": "recognition_status", "fieldtype": "Data", "width": 120},
		{"label": _("Settlement Status"), "fieldname": "settlement_status", "fieldtype": "Data", "width": 120},
	]

	conds = [f"se.{F_IS_LOAN_ISSUE}=1", "se.docstatus=1"]
	values = {}
	if filters.get("company"):
		conds.append("se.company=%(company)s")
		values["company"] = filters["company"]
	if filters.get("party_type"):
		conds.append(f"se.{F_PARTY_TYPE}=%(party_type)s")
		values["party_type"] = filters["party_type"]
	if filters.get("party"):
		conds.append(f"se.{F_PARTY}=%(party)s")
		values["party"] = filters["party"]

	rows = frappe.db.sql(
		f"""
		select se.name as issue, se.company, se.posting_date as issue_date,
			se.{F_PARTY_TYPE} as party_type, se.{F_PARTY} as party,
			se.{F_EXPECTED_RETURN_DATE} as expected_return_date,
			se.{F_PHYSICAL_STATUS} as physical_status,
			se.{F_RECOGNITION_STATUS} as recognition_status,
			se.{F_SETTLEMENT_STATUS} as settlement_status,
			sed.name as detail, sed.item_code, sed.batch_no,
			coalesce(sed.transfer_qty, sed.qty) as issued_qty,
			sed.{F_ISSUE_RATE} as frozen_rate
		from `tabStock Entry` se
		inner join `tabStock Entry Detail` sed on sed.parent = se.name
		where {' and '.join(conds)}
		order by se.posting_date, se.name
		""",
		values,
		as_dict=True,
	)

	data = []
	for r in rows:
		returned = get_returned_qty(r.detail)
		outstanding = flt(r.issued_qty) - flt(returned)
		if outstanding <= 1e-9 and not filters.get("include_fully_returned"):
			continue
		data.append(
			{
				**r,
				"returned_qty": returned,
				"outstanding_qty": outstanding,
				"outstanding_value": flt(outstanding) * flt(r.frozen_rate),
			}
		)
	return columns, data
