"""Ensure PM Holder link fields use title display in desk (show_title_field_in_link)."""

from __future__ import annotations

import frappe


def execute():
	frappe.db.sql(
		"""
		UPDATE `tabDocType`
		SET show_title_field_in_link = 1, title_field = 'employee_name'
		WHERE name = 'PM Holder'
		"""
	)
	frappe.db.sql(
		"""
		UPDATE `tabDocField`
		SET hidden = 0
		WHERE parent = 'PM Holder' AND fieldname = 'employee_name'
		"""
	)
	frappe.clear_cache(doctype="PM Holder")
