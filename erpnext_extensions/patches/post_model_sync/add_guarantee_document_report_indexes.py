# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT
"""Add composite index for Guarantee Document report KPIs.

Index: (status, guarantee_direction, expiry_date)
Idempotent — skips if the index already exists.
"""

from __future__ import annotations

import frappe

INDEX_NAME = "idx_gd_status_direction_expiry"
TABLE = "tabGuarantee Document"


def execute() -> None:
	if not frappe.db.exists("DocType", "Guarantee Document"):
		return
	if not frappe.db.table_exists("Guarantee Document"):
		return

	db_name = frappe.db.sql("SELECT DATABASE()")[0][0]
	exists = frappe.db.sql(
		"""
		SELECT 1
		FROM INFORMATION_SCHEMA.STATISTICS
		WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND INDEX_NAME=%s
		LIMIT 1
		""",
		(db_name, TABLE, INDEX_NAME),
	)
	if exists:
		return

	frappe.db.sql(
		f"""
		ALTER TABLE `{TABLE}`
		ADD INDEX `{INDEX_NAME}` (`status`, `guarantee_direction`, `expiry_date`)
		"""
	)
	frappe.logger("erpnext_extensions").info(
		"Added index %s on %s (status, guarantee_direction, expiry_date)", INDEX_NAME, TABLE
	)
