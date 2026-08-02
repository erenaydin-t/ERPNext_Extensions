# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

"""Make Stock Entry Detail.allow_alternative_item usable outside Work Orders.

Companion to ``erpnext_extensions.stock_extensions.mr_alternative_item``
(alternative items against Material Requests). Two site-level adjustments:

1. Retire the ``fetch_from = bom_no.allow_alternative_item`` Property Setter:
   it forces the flag back to 0 on any entry without a BOM, so the standard
   "Alternate Item" button could never appear for Material Issue / Transfer
   entries created from a Material Request.

2. Set ``read_only = 0`` on the field so warehouse users can tick it on rows
   mapped from a Material Request (upstream marks it read-only because only
   Work Order mapping was expected to set it).

Idempotent; safe to re-run.
"""

from __future__ import annotations

import frappe
from frappe.custom.doctype.property_setter.property_setter import make_property_setter

DT = "Stock Entry Detail"
FIELD = "allow_alternative_item"


def execute():
	for name in frappe.get_all(
		"Property Setter",
		filters={"doc_type": DT, "field_name": FIELD, "property": "fetch_from"},
		pluck="name",
	):
		frappe.delete_doc("Property Setter", name, force=True, ignore_permissions=True)

	make_property_setter(DT, FIELD, "read_only", 0, "Check", validate_fields_for_doctype=False)

	frappe.clear_cache(doctype="Stock Entry")
