# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT
"""Widen account-currency amount columns on GL Entry and Account Closing Balance to DECIMAL(30,9).

Idempotent: reads INFORMATION_SCHEMA; skips missing columns and columns already at target.
Complements expand_currency_precision / v2 for sites where these four columns remain decimal(21,9).
"""

from __future__ import annotations

import frappe

TARGET_PRECISION = 30
TARGET_SCALE = 9

TABLES_AND_COLUMNS: dict[str, list[str]] = {
	"tabAccount Closing Balance": [
		"debit_in_account_currency",
		"credit_in_account_currency",
	],
	"tabGL Entry": [
		"debit_in_account_currency",
		"credit_in_account_currency",
	],
}


def execute() -> None:
	db = frappe.db
	db_name = db.sql("SELECT DATABASE()")[0][0]
	logger = frappe.logger("erpnext_extensions.expand_currency_precision_gl_and_closing_balance")

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

	def ensure_decimal(table: str, col: str, p: int, s: int) -> None:
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

		db.sql(
			f"""
			ALTER TABLE `{table}`
			MODIFY `{col}` DECIMAL({p},{s}) NOT NULL DEFAULT 0
			"""
		)
		logger.info("Updated %s.%s to DECIMAL(%s,%s)", table, col, p, s)

	logger.info("Starting expand_currency_precision_gl_and_closing_balance")
	for table, cols in TABLES_AND_COLUMNS.items():
		for col in cols:
			ensure_decimal(table, col, TARGET_PRECISION, TARGET_SCALE)
	logger.info("Completed expand_currency_precision_gl_and_closing_balance")
	db.commit()
