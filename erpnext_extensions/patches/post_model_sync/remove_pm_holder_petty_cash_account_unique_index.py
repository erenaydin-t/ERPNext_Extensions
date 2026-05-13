from __future__ import annotations

import frappe
from frappe.database.utils import drop_index_if_exists


def execute():
	"""Allow multiple PM Holders in a company to share one petty cash GL account."""
	if not frappe.db.has_table("tabPM Holder"):
		return
	if frappe.conf.get("db_type") == "postgres":
		return

	try:
		indexes = frappe.db.sql(
			"""
			select INDEX_NAME, group_concat(COLUMN_NAME order by SEQ_IN_INDEX) as columns_in_index
			from information_schema.STATISTICS
			where TABLE_SCHEMA = DATABASE()
				and TABLE_NAME = 'tabPM Holder'
				and NON_UNIQUE = 0
				and INDEX_NAME != 'PRIMARY'
			group by INDEX_NAME
			"""
		)
	except Exception:
		return

	for idx_name, columns_in_index in indexes or []:
		columns = [c.strip() for c in (columns_in_index or "").split(",") if c.strip()]
		if "petty_cash_account" not in columns:
			continue
		drop_index_if_exists("tabPM Holder", idx_name)

