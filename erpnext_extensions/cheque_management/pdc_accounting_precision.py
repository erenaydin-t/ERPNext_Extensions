# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT
"""DECIMAL(30,9) columns for Post Dated Cheque accounting lifecycle (JE / GL / Payment Ledger)."""

from __future__ import annotations

import frappe

TARGET_PRECISION = 30
TARGET_SCALE = 9

# MariaDB table name -> amount/currency columns used when PDC posts accounting entries.
PDC_ACCOUNTING_LEDGER_TABLES: dict[str, tuple[str, ...]] = {
	"tabPayment Ledger Entry": (
		"amount",
		"amount_in_account_currency",
	),
	"tabJournal Entry Account": (
		"debit",
		"credit",
		"debit_in_account_currency",
		"credit_in_account_currency",
	),
	"tabJournal Entry": (
		"total_debit",
		"total_credit",
		"difference",
		"total_amount",
	),
	"tabGL Entry": (
		"debit",
		"credit",
		"debit_in_account_currency",
		"credit_in_account_currency",
		"debit_in_transaction_currency",
		"credit_in_transaction_currency",
	),
	"tabPost Dated Cheque": (
		"cheque_amount",
		"allocated_amount",
		"unallocated_amount",
	),
	"tabPDC Allocation": ("amount",),
	"tabPDC Journal Reference": ("amount",),
	"tabGuarantee Document": ("amount",),
}

# DocType -> Currency/amount fields for pre_model_sync property setters (field `length`).
PDC_ACCOUNTING_LEDGER_DOCTYPE_FIELDS: dict[str, tuple[str, ...]] = {
	"Payment Ledger Entry": ("amount", "amount_in_account_currency"),
}


def read_column_numeric_precision_scale(table: str, column: str) -> tuple[int | None, int | None]:
	db_name = frappe.db.sql("SELECT DATABASE()")[0][0]
	row = frappe.db.sql(
		"""
		SELECT NUMERIC_PRECISION, NUMERIC_SCALE
		FROM INFORMATION_SCHEMA.COLUMNS
		WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND COLUMN_NAME=%s
		""",
		(db_name, table, column),
		as_dict=True,
	)
	if not row:
		return None, None
	prec = row[0].get("NUMERIC_PRECISION")
	scale = row[0].get("NUMERIC_SCALE")
	if prec is None or scale is None:
		return None, None
	return int(prec), int(scale)


def column_meets_target(table: str, column: str, p: int = TARGET_PRECISION, s: int = TARGET_SCALE) -> bool:
	cur_p, cur_s = read_column_numeric_precision_scale(table, column)
	if cur_p is None or cur_s is None:
		return False
	return cur_p >= p and cur_s >= s


def ensure_decimal_column(
	table: str,
	column: str,
	p: int = TARGET_PRECISION,
	s: int = TARGET_SCALE,
	logger=None,
) -> bool:
	"""ALTER column to DECIMAL(p,s) when below target. Returns True if ALTER ran."""
	log = logger or frappe.logger("erpnext_extensions.pdc_accounting_precision")
	cur_p, cur_s = read_column_numeric_precision_scale(table, column)
	if cur_p is None and cur_s is None:
		log.warning("Skipping missing column %s.%s", table, column)
		return False

	log.info(
		"Checking %s.%s: current=(%s,%s), target=(%s,%s)",
		table,
		column,
		cur_p,
		cur_s,
		p,
		s,
	)
	if cur_p is not None and cur_p >= p and cur_s is not None and cur_s >= s:
		return False

	frappe.db.sql(
		f"""
		ALTER TABLE `{table}`
		MODIFY `{column}` DECIMAL({p},{s}) NOT NULL DEFAULT 0
		"""
	)
	log.info("Updated %s.%s to DECIMAL(%s,%s)", table, column, p, s)
	return True


def expand_pdc_accounting_ledger_amount_precision() -> None:
	logger = frappe.logger("erpnext_extensions.expand_pdc_accounting_ledger_amount_precision")
	logger.info("Starting expand_pdc_accounting_ledger_amount_precision")
	for table, cols in PDC_ACCOUNTING_LEDGER_TABLES.items():
		for col in cols:
			ensure_decimal_column(table, col, logger=logger)

	db_name = frappe.db.sql("SELECT DATABASE()")[0][0]
	words_table = "tabJournal Entry"
	words_col = "total_amount_in_words"
	row = frappe.db.sql(
		"""
		SELECT CHARACTER_MAXIMUM_LENGTH FROM INFORMATION_SCHEMA.COLUMNS
		WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND COLUMN_NAME=%s
		""",
		(db_name, words_table, words_col),
		as_dict=True,
	)
	if row:
		cur_len = row[0].get("CHARACTER_MAXIMUM_LENGTH")
		target_len = 300
		if cur_len is None or int(cur_len) < target_len:
			frappe.db.sql(
				f"ALTER TABLE `{words_table}` MODIFY `{words_col}` VARCHAR({target_len})"
			)
			logger.info("Updated %s.%s to VARCHAR(%s)", words_table, words_col, target_len)

	logger.info("Completed expand_pdc_accounting_ledger_amount_precision")
	frappe.db.commit()


def audit_required_columns() -> list[tuple[str, str, int | None, int | None]]:
	"""Return rows (table, column, precision, scale) for required columns."""
	out: list[tuple[str, str, int | None, int | None]] = []
	for table, cols in PDC_ACCOUNTING_LEDGER_TABLES.items():
		for col in cols:
			p, s = read_column_numeric_precision_scale(table, col)
			out.append((table, col, p, s))
	return out
