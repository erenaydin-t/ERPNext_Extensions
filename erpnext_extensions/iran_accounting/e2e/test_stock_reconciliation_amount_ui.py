# Copyright (c) 2026, ERPNext Extensions contributors
"""Desk/API gate: Stock Reconciliation amounts match DB and consistency checks."""

from __future__ import annotations

import unittest

import frappe
from frappe.utils import flt

from erpnext_extensions.iran_accounting.e2e_bootstrap import ensure_test_item, get_irr_company, get_warehouse
from erpnext_extensions.iran_accounting.qty_rate_consistency import check_qty_rate_amount_consistency
from erpnext_extensions.iran_accounting.rounding import get_company_currency, round_currency
from erpnext_extensions.iran_accounting.stock_reconciliation_debug import _create_opening_sr


class TestStockReconciliationAmountUI(unittest.TestCase):
	"""API-level stand-in for Desk: doc fields == DB == ledger checks."""

	def setUp(self):
		from erpnext_extensions.iran_accounting.integration.bootstrap import apply

		apply()
		frappe.set_user("Administrator")
		self.company = get_irr_company(None)
		self.warehouse = get_warehouse(self.company)

	def test_submitted_sr_ui_fields_match_db_and_ledger(self):
		item = ensure_test_item(self.company, prefix="IA-SR-UI-UT")
		sr = _create_opening_sr(self.company, self.warehouse, item, 3, valuation_rate=1111.11)
		frappe.db.commit()
		db_header = flt(frappe.db.get_value("Stock Reconciliation", sr.name, "difference_amount"))
		self.assertEqual(db_header, flt(sr.difference_amount))
		rows = frappe.get_all(
			"Stock Reconciliation Item",
			filters={"parent": sr.name},
			fields=["amount", "amount_difference", "qty", "valuation_rate"],
		)
		self.assertTrue(rows)
		for r in rows:
			self.assertIsNotNone(r.amount)
			if flt(r.qty) and r.valuation_rate not in (None, ""):
				self.assertNotEqual(r.amount, "")
		from erpnext_extensions.iran_accounting.domain.qty_rate_amount import (
			sum_stock_reconciliation_amount_difference,
		)

		sum_base = flt(sum_stock_reconciliation_amount_difference(sr))
		self.assertEqual(db_header, sum_base)
		chk = check_qty_rate_amount_consistency("Stock Reconciliation", sr.name, self.company)
		self.assertEqual(chk["status"], "PASS", chk.get("totals"))
