# Copyright (c) 2026, ERPNext Extensions contributors

from __future__ import annotations

import unittest

import frappe
from frappe.utils import flt, nowtime, today

from erpnext_extensions.iran_accounting.domain.qty_rate_amount import (
	compute_final_difference_amount,
	compute_row_amount,
	sum_stock_reconciliation_amount_difference,
	sum_stock_reconciliation_row_amounts,
)
from erpnext_extensions.iran_accounting.e2e_bootstrap import ensure_test_item, get_irr_company, get_warehouse
from erpnext_extensions.iran_accounting.rounding import get_company_currency
from erpnext_extensions.iran_accounting.stock_reconciliation_debug import _create_opening_sr


class TestOpeningVsNormalStockReconciliationDifference(unittest.TestCase):
	def setUp(self):
		from erpnext_extensions.iran_accounting.integration.bootstrap import apply

		apply()
		frappe.set_user("Administrator")
		self.company = get_irr_company(None)
		self.warehouse = get_warehouse(self.company)
		self.currency = get_company_currency(self.company)

	def test_opening_stock_qty3_rate9877_current_zero_is_29631(self):
		"""Regression: no 1-rial drift from double row+header rounding."""
		item = ensure_test_item(self.company, prefix="IA-SR-OPEN-9877")
		sr = _create_opening_sr(self.company, self.warehouse, item, 3, valuation_rate=9877)
		frappe.db.commit()
		sr.reload()
		self.assertEqual(flt(sr.difference_amount), 29631)
		self.assertEqual(flt(sr.difference_amount), sum_stock_reconciliation_amount_difference(sr))
		self.assertEqual(flt(sr.items[0].amount), 29631)

	def test_opening_stock_header_is_sum_amount_difference(self):
		item = ensure_test_item(self.company, prefix="IA-SR-OPEN-NM")
		sr = _create_opening_sr(self.company, self.warehouse, item, 2, valuation_rate=333.33)
		frappe.db.commit()
		sr.reload()
		expected = sum_stock_reconciliation_amount_difference(sr)
		self.assertEqual(flt(sr.difference_amount), expected)

	def test_current_amount_reduces_net_header_vs_gross(self):
		item = ensure_test_item(self.company, prefix="IA-SR-CUR-HDR")
		sr = _create_opening_sr(self.company, self.warehouse, item, 2, valuation_rate=1000)
		frappe.db.commit()
		sr.reload()
		if flt(sr.items[0].current_amount) <= 0:
			self.skipTest("no bin stock to test current_amount effect")
		self.assertEqual(flt(sr.difference_amount), sum_stock_reconciliation_amount_difference(sr))
		self.assertNotEqual(
			flt(sr.difference_amount),
			sum_stock_reconciliation_row_amounts(sr, self.currency),
		)

	def test_normal_stock_reconciliation_header_is_sum_amount_difference(self):
		item = ensure_test_item(self.company, prefix="IA-SR-NORM")
		sr = frappe.new_doc("Stock Reconciliation")
		sr.purpose = "Stock Reconciliation"
		sr.company = self.company
		sr.posting_date = today()
		sr.posting_time = nowtime()
		sr.set_posting_time = 1
		sr.expense_account = frappe.get_cached_value("Company", self.company, "stock_adjustment_account")
		sr.cost_center = frappe.get_cached_value("Company", self.company, "cost_center")
		sr.difference_account = sr.expense_account
		sr.append(
			"items",
			{"item_code": item, "warehouse": self.warehouse, "qty": 5, "valuation_rate": 1200.25},
		)
		compute_final_difference_amount(sr)
		expected = sum_stock_reconciliation_amount_difference(sr)
		self.assertEqual(flt(sr.difference_amount), expected)
		self.assertEqual(
			flt(sr.items[0].amount),
			flt(compute_row_amount(sr.items[0], self.currency, rate_field="valuation_rate")),
		)
