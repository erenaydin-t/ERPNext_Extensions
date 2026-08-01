# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

"""Remove obsolete Consignment Stock Settings DocFields retired in 3.8.0 redesign.

Fields removed from the DocType schema (native DocFields, not Custom Fields):
- consignment_inventory_account
- default_cost_center
- default_finance_book

Frappe DocType sync during migrate drops the DocFields / columns.
This patch is an idempotent safety net that also deletes any Custom Field
records with those fieldnames if they were ever created that way.

Existing Consignment Stock Settings documents are preserved.
Old stored values do not require data migration — the fields are intentionally retired.
Inventory account now resolves from Warehouse via standard ERPNext warehouse-account logic.
"""

from __future__ import annotations

import frappe

OBSOLETE_SETTINGS_FIELDS = (
	"consignment_inventory_account",
	"default_cost_center",
	"default_finance_book",
)

SETTINGS_DT = "Consignment Stock Settings"


def execute():
	_delete_obsolete_custom_fields()
	_delete_orphan_docfields()
	frappe.clear_cache(doctype=SETTINGS_DT)


def _delete_obsolete_custom_fields() -> None:
	for fieldname in OBSOLETE_SETTINGS_FIELDS:
		names = frappe.get_all(
			"Custom Field",
			filters={"dt": SETTINGS_DT, "fieldname": fieldname},
			pluck="name",
		)
		for name in names:
			frappe.delete_doc("Custom Field", name, force=True, ignore_permissions=True)


def _delete_orphan_docfields() -> None:
	"""Remove leftover DocField rows if DocType sync left them (idempotent)."""
	if not frappe.db.exists("DocType", SETTINGS_DT):
		return
	for fieldname in OBSOLETE_SETTINGS_FIELDS:
		names = frappe.get_all(
			"DocField",
			filters={"parent": SETTINGS_DT, "fieldname": fieldname},
			pluck="name",
		)
		for name in names:
			frappe.delete_doc("DocField", name, force=True, ignore_permissions=True)
		# Drop leftover column if still present after DocField removal
		if frappe.db.has_column(SETTINGS_DT, fieldname):
			frappe.db.sql_ddl(f"alter table `tab{SETTINGS_DT}` drop column `{fieldname}`")
