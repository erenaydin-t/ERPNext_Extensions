"""Desk search / link title overrides for Petty Management."""

from __future__ import annotations

import frappe
from frappe.desk.search import get_link_title as frappe_get_link_title


@frappe.whitelist()
def get_link_title(doctype: str, docname: str):
	if doctype == "PM Holder" and docname:
		row = frappe.db.get_value(
			"PM Holder",
			docname,
			["employee_name", "employee"],
			as_dict=True,
		)
		if row:
			from erpnext_extensions.petty_management.services.holder_display import format_pm_holder_title

			return format_pm_holder_title(row.employee_name, row.employee, docname)
	return frappe_get_link_title(doctype, docname)
