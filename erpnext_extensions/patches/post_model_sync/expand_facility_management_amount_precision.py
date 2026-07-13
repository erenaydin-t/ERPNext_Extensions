# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT
"""Widen Facility Management Currency columns to DECIMAL(30,9).

Idempotent: only ALTER when existing numeric precision/scale is below target.
"""

from __future__ import annotations

import frappe

from erpnext_extensions.facility_management.facility_precision import (
	TABLES_AND_COLUMNS,
	TARGET_PRECISION,
	TARGET_SCALE,
)


def execute() -> None:
	db = frappe.db
	db_name = db.sql("SELECT DATABASE()")[0][0]
	logger = frappe.logger("erpnext_extensions.expand_facility_management_amount_precision")

	def current_numeric_pd(table: str, col: str) -> tuple[int | None, int | None]:
		row = db.sql(
			"""
			SELECT NUMERIC_PRECISION, NUMERIC_SCALE, IS_NULLABLE, COLUMN_DEFAULT
			FROM INFORMATION_SCHEMA.COLUMNS
			WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND COLUMN_NAME=%s
			""",
			(db_name, table, col),
			as_dict=True,
		)
		if not row:
			return None, None
		return row[0].get("NUMERIC_PRECISION"), row[0].get("NUMERIC_SCALE")

	def column_nullable(table: str, col: str) -> bool:
		row = db.sql(
			"""
			SELECT IS_NULLABLE FROM INFORMATION_SCHEMA.COLUMNS
			WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND COLUMN_NAME=%s
			""",
			(db_name, table, col),
			as_dict=True,
		)
		if not row:
			return False
		return (row[0].get("IS_NULLABLE") or "").upper() == "YES"

	def ensure_decimal(table: str, col: str) -> None:
		cur_p, cur_s = current_numeric_pd(table, col)
		if cur_p is None and cur_s is None:
			logger.warning("Skipping missing column %s.%s", table, col)
			return

		logger.info(
			"Checking %s.%s: current=(%s,%s), target=(%s,%s)",
			table,
			col,
			cur_p,
			cur_s,
			TARGET_PRECISION,
			TARGET_SCALE,
		)

		if (cur_p is not None and cur_p >= TARGET_PRECISION) and (
			cur_s is not None and cur_s >= TARGET_SCALE
		):
			return

		nullable = column_nullable(table, col)
		null_sql = "NULL" if nullable else "NOT NULL DEFAULT 0"
		db.sql(
			f"""
			ALTER TABLE `{table}`
			MODIFY `{col}` DECIMAL({TARGET_PRECISION},{TARGET_SCALE}) {null_sql}
			"""
		)
		logger.info("Updated %s.%s to DECIMAL(%s,%s)", table, col, TARGET_PRECISION, TARGET_SCALE)

	logger.info("Starting expand_facility_management_amount_precision")
	for table, cols in TABLES_AND_COLUMNS.items():
		for col in cols:
			ensure_decimal(table, col)
	logger.info("Completed expand_facility_management_amount_precision")
	db.commit()
