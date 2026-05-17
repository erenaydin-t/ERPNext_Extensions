from __future__ import annotations

import frappe
from frappe.database.utils import drop_index_if_exists


def execute():
	"""Drop legacy UNIQUE index on `employee` if present (multi-company holders use employee+company)."""
	if not frappe.db.has_table("tabPM Holder"):
		return
	if frappe.conf.get("db_type") == "postgres":
		return
	try:
		indexes = frappe.db.sql(
			"""
			select distinct INDEX_NAME
			from information_schema.STATISTICS
			where TABLE_SCHEMA = DATABASE()
				and TABLE_NAME = 'tabPM Holder'
				and COLUMN_NAME = 'employee'
				and NON_UNIQUE = 0
				and INDEX_NAME != 'PRIMARY'
			"""
		)
	except Exception:
		return
	for (idx_name,) in indexes or []:
		if not idx_name:
			continue
		drop_index_if_exists("tabPM Holder", idx_name)
