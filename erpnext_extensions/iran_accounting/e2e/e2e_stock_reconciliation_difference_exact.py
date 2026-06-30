# Copyright (c) 2026, ERPNext Extensions contributors
"""Submit/cancel/resubmit: difference_amount stays Σ row.amount with no drift."""

from __future__ import annotations

import unittest

import frappe
from frappe.utils import flt

from erpnext_extensions.iran_accounting.domain.qty_rate_amount import (
	sum_stock_reconciliation_amount_difference,
)
from erpnext_extensions.iran_accounting.e2e_bootstrap import ensure_test_item, get_irr_company, get_warehouse
from erpnext_extensions.iran_accounting.rounding import get_company_currency
from erpnext_extensions.iran_accounting.stock_reconciliation_debug import _create_opening_sr


class E2EStockReconciliationDifferenceExact(unittest.TestCase):
	def setUp(self):
		from erpnext_extensions.iran_accounting.integration.bootstrap import apply

		apply()
		frappe.set_user("Administrator")
		self.company = get_irr_company(None)
		self.warehouse = get_warehouse(self.company)
		self.currency = get_company_currency(self.company)

	def _expected(self, doc) -> float:
		return flt(sum_stock_reconciliation_amount_difference(doc))

	def test_submit_cancel_resubmit_identical_difference(self):
		item = ensure_test_item(self.company, prefix="IA-SR-E2E-EX")
		sr = _create_opening_sr(self.company, self.warehouse, item, 3, valuation_rate=9877)
		frappe.db.commit()
		expected = self._expected(sr)
		db_val = flt(frappe.db.get_value("Stock Reconciliation", sr.name, "difference_amount"))
		self.assertEqual(db_val, expected)
		self.assertEqual(flt(sr.difference_amount), expected)

		sr.cancel()
		frappe.db.commit()

		item2 = ensure_test_item(self.company, prefix="IA-SR-E2E-EX2")
		sr2 = _create_opening_sr(self.company, self.warehouse, item2, 3, valuation_rate=9877)
		frappe.db.commit()
		expected2 = self._expected(sr2)
		self.assertEqual(flt(sr2.difference_amount), expected2)
		self.assertEqual(expected, expected2)
