# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT
"""Widen Stock Reconciliation parent/child amount/rate/qty columns to DECIMAL(30,9).

Discovers fields from Stock Reconciliation meta (parent + Table child doctypes).
Idempotent: skips missing tables/columns and columns already at DECIMAL(30,9).
"""

from __future__ import annotations

import frappe

from erpnext_extensions.stock_reconciliation_precision import (
	TARGET_PRECISION,
	TARGET_SCALE,
	stock_reconciliation_tables_and_columns,
)


def execute() -> None:
	db = frappe.db
	db_name = db.sql("SELECT DATABASE()")[0][0]
	logger = frappe.logger("erpnext_extensions.expand_stock_reconciliation_amount_precision")

	tables_and_columns = stock_reconciliation_tables_and_columns()
	if not tables_and_columns:
		logger.warning("No Stock Reconciliation tables/fields found; nothing to expand")
		return

	def current_numeric_pd(table: str, col: str) -> tuple[int | None, int | None]:
		row = db.sql(
			"""
			SELECT NUMERIC_PRECISION, NUMERIC_SCALE
			FROM INFORMATION_SCHEMA.COLUMNS
			WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND COLUMN_NAME=%s
			""",
			(db_name, table, col),
			as_dict=True,
		)
		if not row:
			return None, None
		prec = row[0].get("NUMERIC_PRECISION")
		scale = row[0].get("NUMERIC_SCALE")
		if prec is None or scale is None:
			return None, None
		return int(prec), int(scale)

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

	def ensure_decimal(table: str, col: str, p: int, s: int) -> None:
		if not frappe.db.table_exists(table):
			logger.warning("Skipping missing table %s", table)
			return

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
			p,
			s,
		)

		if (cur_p is not None and cur_p >= p) and (cur_s is not None and cur_s >= s):
			logger.info(
				"Skipping %s.%s: already at or above DECIMAL(%s,%s)",
				table,
				col,
				p,
				s,
			)
			return

		nullable = column_nullable(table, col)
		null_sql = "NULL" if nullable else "NOT NULL DEFAULT 0"
		db.sql(
			f"""
			ALTER TABLE `{table}`
			MODIFY `{col}` DECIMAL({p},{s}) {null_sql}
			"""
		)
		logger.info("Updated %s.%s to DECIMAL(%s,%s)", table, col, p, s)

	logger.info("Starting expand_stock_reconciliation_amount_precision")
	for table, cols in tables_and_columns.items():
		for col in cols:
			ensure_decimal(table, col, TARGET_PRECISION, TARGET_SCALE)
	logger.info("Completed expand_stock_reconciliation_amount_precision")
	db.commit()
