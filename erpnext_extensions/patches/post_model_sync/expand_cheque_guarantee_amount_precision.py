# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT
"""Widen Currency amount columns for Cheque Management and Guarantee Management to DECIMAL(30,9).

Idempotent: only ALTER when existing numeric precision/scale is below target.
Does not touch ERPNext core JE/GL/PE tables (see expand_currency_precision / v2).
"""

from __future__ import annotations

import frappe

TARGET_PRECISION = 30
TARGET_SCALE = 9

# table name (with tab prefix) -> column names (Currency fields stored as DECIMAL in MariaDB)
TABLES_AND_COLUMNS: dict[str, list[str]] = {
	"tabPost Dated Cheque": [
		"cheque_amount",
		"allocated_amount",
		"unallocated_amount",
	],
	"tabGuarantee Document": [
		"amount",
	],
	# Child tables of Post Dated Cheque (amounts follow parent cheque / JE reference)
	"tabPDC Allocation": [
		"amount",
	],
	"tabPDC Journal Reference": [
		"amount",
	],
}


def execute() -> None:
	db = frappe.db
	db_name = db.sql("SELECT DATABASE()")[0][0]
	logger = frappe.logger("erpnext_extensions.expand_cheque_guarantee_amount_precision")

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
		return row[0].get("NUMERIC_PRECISION"), row[0].get("NUMERIC_SCALE")

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

		if (cur_p is not None and cur_p >= TARGET_PRECISION) and (cur_s is not None and cur_s >= TARGET_SCALE):
			return

		db.sql(
			f"""
			ALTER TABLE `{table}`
			MODIFY `{col}` DECIMAL({TARGET_PRECISION},{TARGET_SCALE}) NOT NULL DEFAULT 0
			"""
		)
		logger.info("Updated %s.%s to DECIMAL(%s,%s)", table, col, TARGET_PRECISION, TARGET_SCALE)

	frappe.logger().info("Starting expand_cheque_guarantee_amount_precision")
	for table, cols in TABLES_AND_COLUMNS.items():
		for col in cols:
			ensure_decimal(table, col)
	frappe.logger().info("Completed expand_cheque_guarantee_amount_precision")
	db.commit()
