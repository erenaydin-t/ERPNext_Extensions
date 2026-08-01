# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import date_diff, flt, getdate, today

from erpnext_extensions.consignment_stock.material_loan.constants import (
	F_IS_LOAN_ISSUE,
	F_ISSUE_RATE,
	F_PARTY,
)
from erpnext_extensions.consignment_stock.material_loan.returnable_qty import get_returned_qty


def execute(filters=None):
	filters = filters or {}
	columns = [
		{"label": _("Party"), "fieldname": "party", "fieldtype": "Data", "width": 140},
		{"label": _("Item"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 120},
		{"label": _("Outstanding Qty"), "fieldname": "outstanding_qty", "fieldtype": "Float", "width": 110},
		{"label": _("Outstanding Value"), "fieldname": "outstanding_value", "fieldtype": "Currency", "width": 120},
		{"label": _("Days Outstanding"), "fieldname": "days_outstanding", "fieldtype": "Int", "width": 110},
		{"label": _("0–30"), "fieldname": "age_0_30", "fieldtype": "Currency", "width": 100},
		{"label": _("31–60"), "fieldname": "age_31_60", "fieldtype": "Currency", "width": 100},
		{"label": _("61–90"), "fieldname": "age_61_90", "fieldtype": "Currency", "width": 100},
		{"label": _("90+"), "fieldname": "age_90_plus", "fieldtype": "Currency", "width": 100},
	]

	conds = [f"se.{F_IS_LOAN_ISSUE}=1", "se.docstatus=1"]
	values = {}
	if filters.get("company"):
		conds.append("se.company=%(company)s")
		values["company"] = filters["company"]

	rows = frappe.db.sql(
		f"""
		select se.{F_PARTY} as party, se.posting_date, sed.item_code, sed.name as detail,
			coalesce(sed.transfer_qty, sed.qty) as issued_qty, sed.{F_ISSUE_RATE} as frozen_rate
		from `tabStock Entry` se
		inner join `tabStock Entry Detail` sed on sed.parent=se.name
		where {' and '.join(conds)}
		""",
		values,
		as_dict=True,
	)

	agg = {}
	as_of = getdate(today())
	for r in rows:
		outstanding = flt(r.issued_qty) - flt(get_returned_qty(r.detail))
		if outstanding <= 1e-9:
			continue
		value = outstanding * flt(r.frozen_rate)
		days = date_diff(as_of, getdate(r.posting_date))
		key = (r.party, r.item_code)
		bucket = agg.setdefault(
			key,
			{
				"party": r.party,
				"item_code": r.item_code,
				"outstanding_qty": 0.0,
				"outstanding_value": 0.0,
				"days_outstanding": 0,
				"age_0_30": 0.0,
				"age_31_60": 0.0,
				"age_61_90": 0.0,
				"age_90_plus": 0.0,
			},
		)
		bucket["outstanding_qty"] += outstanding
		bucket["outstanding_value"] += value
		bucket["days_outstanding"] = max(bucket["days_outstanding"], days)
		if days <= 30:
			bucket["age_0_30"] += value
		elif days <= 60:
			bucket["age_31_60"] += value
		elif days <= 90:
			bucket["age_61_90"] += value
		else:
			bucket["age_90_plus"] += value

	return columns, list(agg.values())
