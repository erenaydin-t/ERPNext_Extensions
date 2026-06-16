# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt, getdate

from erpnext_extensions.facility_management.facility_balances import get_facility_balance_row
from erpnext_extensions.facility_management.facility_report_filters import apply_facility_filters_to_sql


def execute(filters=None):
	filters = frappe._dict(filters or {})
	columns = get_columns()
	data = get_data(filters)
	return columns, data


def get_columns():
	return [
		{"label": _("Facility"), "fieldname": "facility", "fieldtype": "Link", "options": "Facility", "width": 140},
		{"label": _("Facility Name"), "fieldname": "facility_name", "fieldtype": "Data", "width": 160},
		{"label": _("Facility Type"), "fieldname": "facility_type", "fieldtype": "Link", "options": "Facility Type", "width": 140},
		{"label": _("Bank"), "fieldname": "bank", "fieldtype": "Link", "options": "Bank", "width": 120},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 90},
		{"label": _("Principal"), "fieldname": "principal_amount", "fieldtype": "Currency", "width": 120},
		{"label": _("Profit"), "fieldname": "profit_amount", "fieldtype": "Currency", "width": 120},
		{"label": _("Paid Principal"), "fieldname": "paid_principal", "fieldtype": "Currency", "width": 120},
		{"label": _("Paid Profit"), "fieldname": "paid_profit", "fieldtype": "Currency", "width": 120},
		{"label": _("Paid Penalty"), "fieldname": "paid_penalty", "fieldtype": "Currency", "width": 110},
		{"label": _("Remaining Principal"), "fieldname": "remaining_principal", "fieldtype": "Currency", "width": 130},
		{"label": _("Remaining Profit"), "fieldname": "remaining_profit", "fieldtype": "Currency", "width": 120},
		{"label": _("Remaining Total"), "fieldname": "remaining_total", "fieldtype": "Currency", "width": 120},
		{"label": _("Opening"), "fieldname": "is_opening_facility", "fieldtype": "Check", "width": 80},
	]


def get_data(filters):
	filters = frappe._dict(filters or {})
	if not filters.get("company"):
		frappe.throw(_("Company is required"))
	conditions = ["company = %(company)s"]
	params = {"company": filters.company}
	if filters.get("bank"):
		conditions.append("bank = %(bank)s")
		params["bank"] = filters.bank
	if filters.get("status"):
		conditions.append("status = %(status)s")
		params["status"] = filters.status
	apply_facility_filters_to_sql(conditions, params, filters)
	as_on = filters.get("as_on_date")
	names = frappe.db.sql_list(
		f"SELECT name FROM `tabFacility` WHERE {' AND '.join(conditions)} ORDER BY name",
		params,
	)
	data = []
	for name in names:
		row = get_facility_balance_row(name, as_on_date=as_on)
		data.append(row)
	return data
