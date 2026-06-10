# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT
"""Unit tests for PDC accounting DECIMAL(30,9) column lists and patch idempotency."""

from __future__ import annotations

import unittest

import frappe

from erpnext_extensions.cheque_management.pdc_accounting_precision import (
	PDC_ACCOUNTING_LEDGER_TABLES,
	TARGET_PRECISION,
	TARGET_SCALE,
	audit_required_columns,
	column_meets_target,
	expand_pdc_accounting_ledger_amount_precision,
)
from erpnext_extensions.patches.post_model_sync.expand_pdc_accounting_ledger_amount_precision import (
	execute as expand_pdc_accounting_ledger_execute,
)


class TestPDCAccountingLedgerPrecisionColumns(unittest.TestCase):
	def test_payment_ledger_entry_amount_included(self):
		cols = PDC_ACCOUNTING_LEDGER_TABLES.get("tabPayment Ledger Entry", ())
		self.assertIn("amount", cols)
		self.assertIn("amount_in_account_currency", cols)

	def test_journal_entry_account_debit_credit_included(self):
		cols = PDC_ACCOUNTING_LEDGER_TABLES.get("tabJournal Entry Account", ())
		for name in ("debit", "credit", "debit_in_account_currency", "credit_in_account_currency"):
			self.assertIn(name, cols)

	def test_gl_entry_debit_credit_included(self):
		cols = PDC_ACCOUNTING_LEDGER_TABLES.get("tabGL Entry", ())
		for name in ("debit", "credit", "debit_in_account_currency", "credit_in_account_currency"):
			self.assertIn(name, cols)

	def test_no_missing_required_accounting_columns(self):
		missing = []
		for table, col, prec, scale in audit_required_columns():
			if prec is None and scale is None:
				missing.append(f"{table}.{col}")
		self.assertEqual(missing, [], f"missing columns: {missing}")

	def test_patch_idempotent(self):
		expand_pdc_accounting_ledger_execute()
		before = {
			(t, c): (p, s)
			for t, c, p, s in audit_required_columns()
			if p is not None
		}
		expand_pdc_accounting_ledger_execute()
		after = {
			(t, c): (p, s)
			for t, c, p, s in audit_required_columns()
			if p is not None
		}
		self.assertEqual(before, after)

	def test_payment_ledger_at_target_after_patch(self):
		expand_pdc_accounting_ledger_execute()
		for col in ("amount", "amount_in_account_currency"):
			self.assertTrue(
				column_meets_target("tabPayment Ledger Entry", col, TARGET_PRECISION, TARGET_SCALE),
				col,
			)


if __name__ == "__main__":
	frappe.init(site="development.localhost")
	frappe.connect()
	unittest.main()
