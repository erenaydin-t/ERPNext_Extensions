# Copyright (c) 2026, Farbod Siyahpoosh and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt, getdate, today

from erpnext.accounts.utils import get_balance_on


def execute(filters=None):
	filters = frappe._dict(filters or {})
	columns = [
		{"label": _("Employee"), "fieldname": "employee", "fieldtype": "Link", "options": "Employee", "width": 140},
		{"label": _("Employee Name"), "fieldname": "employee_name", "fieldtype": "Data", "width": 160},
		{"label": _("Company"), "fieldname": "company", "fieldtype": "Link", "options": "Company", "width": 140},
		{"label": _("Petty Cash Account"), "fieldname": "petty_cash_account", "fieldtype": "Link", "options": "Account", "width": 160},
		{"label": _("Current Balance"), "fieldname": "current_balance", "fieldtype": "Currency", "width": 120},
		{"label": _("Last Clearance Date"), "fieldname": "last_clearance_date", "fieldtype": "Date", "width": 140},
	]

	conditions = "1=1"
	params: dict = {}
	if filters.get("company"):
		conditions += " and company = %(company)s"
		params["company"] = filters.company

	holders = frappe.db.sql(
		f"""
		select name, employee, employee_name, company, petty_cash_account
		from `tabPM Holder`
		where {conditions}
		""",
		params,
		as_dict=True,
	)

	as_on = getdate(today())
	data = []
	for h in holders:
		bal = flt(
			get_balance_on(account=h.petty_cash_account, date=as_on, company=h.company)
		)
		if bal <= 0:
			continue
		last_dt = None
		if frappe.db.has_table("tabPM Clearance"):
			last_dt = frappe.db.sql(
				"""
				select max(transaction_date) from `tabPM Clearance`
				where employee=%s and company=%s and docstatus=1
				""",
				(h.employee, h.company),
			)[0][0]
		data.append({**h, "current_balance": bal, "last_clearance_date": last_dt})

	return columns, data
