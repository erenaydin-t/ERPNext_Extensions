# Copyright (c) 2026, Farbod Siyahpoosh and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt, getdate


def execute(filters=None):
	filters = frappe._dict(filters or {})
	if not filters.get("company"):
		frappe.throw(_("Company is required"))

	columns = [
		{"label": _("Date"), "fieldname": "posting_date", "fieldtype": "Date", "width": 100},
		{"label": _("Document Type"), "fieldname": "voucher_type", "fieldtype": "Data", "width": 120},
		{"label": _("Document No"), "fieldname": "voucher_no", "fieldtype": "Dynamic Link", "options": "voucher_type", "width": 140},
		{"label": _("Debit"), "fieldname": "debit", "fieldtype": "Currency", "width": 100},
		{"label": _("Credit"), "fieldname": "credit", "fieldtype": "Currency", "width": 100},
		{"label": _("Balance"), "fieldname": "balance", "fieldtype": "Currency", "width": 120},
		{"label": _("Project"), "fieldname": "project", "fieldtype": "Link", "options": "Project", "width": 140},
		{"label": _("Remarks"), "fieldname": "remarks", "fieldtype": "Data", "width": 200},
	]

	holder_filters = {"company": filters.company}
	if filters.get("employee"):
		holder_filters["employee"] = filters.employee

	accounts = frappe.get_all(
		"PM Holder",
		filters=holder_filters,
		pluck="petty_cash_account",
		distinct=True,
	)
	accounts = [a for a in accounts if a]
	if not accounts:
		return columns, []

	from_date = getdate(filters.get("from_date") or "2000-01-01")
	to_date = getdate(filters.get("to_date") or frappe.utils.today())

	opening = 0.0
	for acc in accounts:
		opening += flt(
			frappe.db.sql(
				"""
				select sum(debit) - sum(credit)
				from `tabGL Entry`
				where account = %s and company = %s and posting_date < %s
				""",
				(acc, filters.company, from_date),
			)[0][0]
			or 0
		)

	rows = frappe.db.sql(
		"""
		select posting_date, voucher_type, voucher_no, debit, credit, project, remarks
		from `tabGL Entry`
		where company = %(company)s
			and account in %(accounts)s
			and posting_date between %(from_date)s and %(to_date)s
			and is_cancelled = 0
		order by posting_date, creation, name
		""",
		{
			"company": filters.company,
			"accounts": tuple(accounts),
			"from_date": from_date,
			"to_date": to_date,
		},
		as_dict=True,
	)

	bal = opening
	data = []
	if opening:
		data.append(
			{
				"posting_date": from_date,
				"voucher_type": "",
				"voucher_no": _("Opening"),
				"debit": opening if opening > 0 else 0,
				"credit": -opening if opening < 0 else 0,
				"balance": bal,
				"project": "",
				"remarks": "",
			}
		)

	for r in rows:
		bal += flt(r.debit) - flt(r.credit)
		r["balance"] = bal
		data.append(r)

	return columns, data
