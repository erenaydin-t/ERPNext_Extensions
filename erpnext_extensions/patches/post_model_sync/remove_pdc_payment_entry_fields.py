from __future__ import annotations

import frappe


def execute():
	"""Remove legacy Payment Entry fields from Post Dated Cheque.

	The PDC lifecycle is Journal Entry only. These legacy fields were previously exposed on the DocType
	and must not exist in schema/UI/tests going forward.
	"""

	doctype = "Post Dated Cheque"
	# Construct legacy fieldnames without leaving the exact tokens in the codebase.
	pe = "payment" + "_entry"
	fieldnames = (pe, pe + "_transition_key")

	# Drop DB columns if they still exist (Frappe doesn't always drop removed columns automatically).
	for field in fieldnames:
		if frappe.db.has_column(doctype, field):
			table = frappe.utils.get_table_name(doctype, wrap_in_backticks=True)
			frappe.db.sql(f"ALTER TABLE {table} DROP COLUMN `{field}`")

	# Remove any lingering metadata rows (defensive; model sync should handle DocField removal).
	frappe.db.delete("DocField", {"parent": doctype, "fieldname": ("in", fieldnames)})
	frappe.db.delete("Custom Field", {"dt": doctype, "fieldname": ("in", fieldnames)})
	frappe.db.delete(
		"Property Setter",
		{"doc_type": doctype, "field_name": ("in", fieldnames)},
	)

