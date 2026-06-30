# Copyright (c) 2026, ERPNext Extensions contributors

from __future__ import annotations

import unittest

import frappe

from erpnext_extensions.iran_accounting.e2e_bootstrap import ensure_test_item, get_irr_company, get_warehouse
from erpnext_extensions.iran_accounting.qty_rate_consistency import check_qty_rate_amount_consistency
from erpnext_extensions.iran_accounting.stock_reconciliation_debug import _create_opening_sr


class TestStockReconciliationQtyRateAlignment(unittest.TestCase):
	def setUp(self):
		import erpnext_extensions.iran_accounting  # noqa: F401
		from erpnext_extensions.iran_accounting.monkey_patches import apply_monkey_patches

		apply_monkey_patches()
		frappe.set_user("Administrator")
		self.company = get_irr_company(None)
		self.warehouse = get_warehouse(self.company)

	def test_opening_fractional_rate_gl_matches_difference_amount(self):
		item = ensure_test_item(self.company, prefix="IA-SR-QR-UT")
		sr = _create_opening_sr(self.company, self.warehouse, item, 3, valuation_rate=1234.567)
		frappe.db.commit()
		chk = check_qty_rate_amount_consistency("Stock Reconciliation", sr.name, self.company)
		self.assertEqual(chk["status"], "PASS", chk)
		totals = chk["totals"]
		self.assertEqual(totals["header_vs_rows_residual"], 0)
		self.assertEqual(totals["difference_vs_gl_residual"], 0)
		self.assertEqual(totals["difference_vs_sle_residual"], 0)
