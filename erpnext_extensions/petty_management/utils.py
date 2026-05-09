# Copyright (c) 2026, Farbod Siyahpoosh and contributors
# For license information, please see license.txt

import frappe


def get_pm_settings():
	if not frappe.db.exists("DocType", "PM Settings"):
		return None
	return frappe.get_single("PM Settings")


def get_pm_holder_name(employee: str, company: str) -> str | None:
	if not employee or not company:
		return None
	return frappe.db.get_value(
		"PM Holder",
		{"employee": employee, "company": company},
		"name",
	)


def employee_has_draft_pm_clearance(employee: str, company: str) -> bool:
	if not frappe.db.has_table("tabPM Clearance"):
		return False
	r = frappe.db.sql(
		"""
		select name from `tabPM Clearance`
		where employee=%s and company=%s and docstatus=0
			and ifnull(status, '') != 'Cancelled'
		limit 1
		""",
		(employee, company),
	)
	return bool(r)
