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
		{"label": _("Max Balance"), "fieldname": "max_balance", "fieldtype": "Currency", "width": 120},
		{"label": _("Current Balance"), "fieldname": "current_balance", "fieldtype": "Currency", "width": 120},
		{"label": _("Pending Settlement"), "fieldname": "pending_clearance_amount", "fieldtype": "Currency", "width": 140},
		{"label": _("Settled Amount"), "fieldname": "consumed_amount", "fieldtype": "Currency", "width": 120},
		{"label": _("Remaining Limit"), "fieldname": "remaining_limit", "fieldtype": "Currency", "width": 120},
	]

	conditions = "1=1"
	params: dict = {}
	if filters.get("company"):
		conditions += " and company = %(company)s"
		params["company"] = filters.company

	holders = frappe.db.sql(
		f"""
		select name, employee, employee_name, company, petty_cash_account, max_balance
		from `tabPM Holder`
		where {conditions}
		order by company, employee
		""",
		params,
		as_dict=True,
	)

	as_on = getdate(today())
	data = []
	for h in holders:
		cur = flt(
			get_balance_on(account=h.petty_cash_account, date=as_on, company=h.company)
		)
		pending = settled = 0.0
		if frappe.db.has_table("tabPM Clearance"):
			pending = flt(
				frappe.db.sql(
					"""
					select coalesce(sum(total_expense_amount), 0) from `tabPM Clearance`
					where employee=%s and company=%s and docstatus=1
					and ifnull(journal_entry,'') = ''
					and ifnull(status,'') != 'Cancelled'
					""",
					(h.employee, h.company),
				)[0][0]
			)
			settled = flt(
				frappe.db.sql(
					"""
					select coalesce(sum(total_expense_amount), 0) from `tabPM Clearance`
					where employee=%s and company=%s and docstatus=1
					and ifnull(journal_entry,'') != ''
					and ifnull(status,'') != 'Cancelled'
					""",
					(h.employee, h.company),
				)[0][0]
			)
		rem = (flt(h.max_balance) - cur) if h.max_balance else None
		row = {
			**h,
			"current_balance": cur,
			"pending_clearance_amount": pending,
			"consumed_amount": settled,
			"remaining_limit": rem,
		}
		data.append(row)

	return columns, data
