from __future__ import annotations

import frappe
from frappe.model import delete_fields


def execute():
	"""Remove scalar Petty Management settlement fields from Purchase Invoice.

	PM settlement is many-to-many. Purchase Invoice must not store one PM Request,
	one PM Clearance, or one PM Holder as settlement truth.
	"""

	doctype = "Purchase Invoice"
	fieldnames = ("custom_pm_request", "custom_pm_clearance", "custom_pm_holder")

	for fieldname in fieldnames:
		custom_field_name = f"{doctype}-{fieldname}"
		if frappe.db.exists("Custom Field", custom_field_name):
			frappe.delete_doc("Custom Field", custom_field_name, ignore_permissions=True, force=True)

	frappe.db.delete("Custom Field", {"dt": doctype, "fieldname": ("in", fieldnames)})
	frappe.db.delete(
		"Property Setter",
		{"doc_type": doctype, "field_name": ("in", fieldnames)},
	)

	_delete_columns(doctype, fieldnames)

	frappe.clear_cache(doctype=doctype)


def _delete_columns(doctype: str, fieldnames: tuple[str, ...]) -> None:
	existing_fieldnames = [fieldname for fieldname in fieldnames if frappe.db.has_column(doctype, fieldname)]
	if not existing_fieldnames:
		return

	delete_column = getattr(frappe.db, "delete_column", None)
	if delete_column:
		for fieldname in existing_fieldnames:
			delete_column(doctype, fieldname)
		return

	# Compatibility fallback for benches where frappe.db.delete_column is not available.
	delete_fields({doctype: existing_fieldnames}, delete=1)

