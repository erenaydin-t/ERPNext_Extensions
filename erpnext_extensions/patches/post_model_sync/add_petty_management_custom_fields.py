from __future__ import annotations

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	common = [
		{
			"fieldname": "custom_pm_request",
			"label": "PM Request",
			"fieldtype": "Link",
			"options": "PM Request",
			"insert_after": "title",
			"read_only": 1,
			"allow_on_submit": 1,
			"module": "Petty Management",
		},
		{
			"fieldname": "custom_pm_clearance",
			"label": "PM Clearance",
			"fieldtype": "Link",
			"options": "PM Clearance",
			"insert_after": "custom_pm_request",
			"read_only": 1,
			"allow_on_submit": 1,
			"module": "Petty Management",
		},
		{
			"fieldname": "custom_pm_holder",
			"label": "PM Holder",
			"fieldtype": "Link",
			"options": "PM Holder",
			"insert_after": "custom_pm_clearance",
			"read_only": 1,
			"allow_on_submit": 1,
			"module": "Petty Management",
		},
	]
	ec_fields = [
		{
			"fieldname": "custom_pm_request",
			"label": "PM Request",
			"fieldtype": "Link",
			"options": "PM Request",
			"insert_after": "remark",
			"read_only": 1,
			"allow_on_submit": 1,
			"module": "Petty Management",
		},
		{
			"fieldname": "custom_pm_clearance",
			"label": "PM Clearance",
			"fieldtype": "Link",
			"options": "PM Clearance",
			"insert_after": "custom_pm_request",
			"read_only": 1,
			"allow_on_submit": 1,
			"module": "Petty Management",
		},
		{
			"fieldname": "custom_pm_holder",
			"label": "PM Holder",
			"fieldtype": "Link",
			"options": "PM Holder",
			"insert_after": "custom_pm_clearance",
			"read_only": 1,
			"allow_on_submit": 1,
			"module": "Petty Management",
		},
	]
	mapping = {
		"Payment Entry": common,
		"Journal Entry": common,
		"Expense Claim": ec_fields,
	}
	to_create = {dt: rows for dt, rows in mapping.items() if frappe.db.exists("DocType", dt)}
	if to_create:
		create_custom_fields(to_create, update=True)
	frappe.clear_cache(doctype="Payment Entry")
	frappe.clear_cache(doctype="Journal Entry")
	if frappe.db.exists("DocType", "Expense Claim"):
		frappe.clear_cache(doctype="Expense Claim")
