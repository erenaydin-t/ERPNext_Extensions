from __future__ import annotations

import frappe


def execute():
	"""Remove obsolete Default Mode of Payment from PDC Settings (JE-only lifecycle; no Payment Entry)."""

	doctype = "PDC Settings"
	field = "default_mode_of_payment"

	if frappe.db.has_column(doctype, field):
		table = frappe.utils.get_table_name(doctype, wrap_in_backticks=True)
		frappe.db.sql(f"ALTER TABLE {table} DROP COLUMN `{field}`")

	frappe.db.delete("DocField", {"parent": doctype, "fieldname": field})
	frappe.db.delete("Custom Field", {"dt": doctype, "fieldname": field})
	frappe.db.delete("Property Setter", {"doc_type": doctype, "field_name": field})
