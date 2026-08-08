# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

"""Frappe v16 Dynamic Link controller repair for Stock Entry party type fields."""

from __future__ import annotations

import frappe

from erpnext_extensions.consignment_stock.constants import F_PARTY_TYPE as CONSIGNMENT_PARTY_TYPE
from erpnext_extensions.consignment_stock.material_loan.constants import (
	F_PARTY_TYPE as MATERIAL_LOAN_PARTY_TYPE,
)

STOCK_ENTRY_PARTY_TYPE_FIELDS = (CONSIGNMENT_PARTY_TYPE, MATERIAL_LOAN_PARTY_TYPE)


def repair_stock_entry_party_type_link_options() -> bool:
	"""Set party-type controller Custom Fields to Link options=DocType.

	Uses ``db.set_value`` so repair works while Stock Entry meta is still invalid
	(Dynamic Link validation would otherwise block Custom Field.save()).

	Returns True if any row was updated.
	"""
	updated = False
	for fieldname in STOCK_ENTRY_PARTY_TYPE_FIELDS:
		name = frappe.db.get_value(
			"Custom Field",
			{"dt": "Stock Entry", "fieldname": fieldname},
			"name",
		)
		if not name:
			continue
		current = frappe.db.get_value("Custom Field", name, "options")
		if current == "DocType":
			continue
		frappe.db.set_value("Custom Field", name, "options", "DocType", update_modified=False)
		updated = True

	if updated:
		frappe.clear_cache(doctype="Stock Entry")
	return updated
