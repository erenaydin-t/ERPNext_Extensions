# Copyright (c) 2026, ERPNext Extensions contributors

from __future__ import annotations

import unittest

import frappe
from frappe.utils import flt

from erpnext_extensions.iran_accounting.domain.qty_rate_amount import (
	compute_row_amount,
	normalize_stock_reconciliation_row,
)
from erpnext_extensions.iran_accounting.e2e_bootstrap import ensure_test_item, get_irr_company, get_warehouse
from erpnext_extensions.iran_accounting.rounding import get_company_currency, get_currency_precision
from erpnext_extensions.iran_accounting.stock_reconciliation_debug import _create_opening_sr


class TestStockReconciliationRowAmount(unittest.TestCase):
	def setUp(self):
		from erpnext_extensions.iran_accounting.integration.bootstrap import apply

		apply()
		frappe.set_user("Administrator")
		self.company = get_irr_company(None)
		self.currency = get_company_currency(self.company)

	def test_compute_row_amount_qty_times_rate_irr_integer(self):
		row = frappe._dict(qty=3, valuation_rate=1234.567)
		amount = compute_row_amount(row, self.currency, rate_field="valuation_rate")
		self.assertEqual(amount, 3704)
		self.assertEqual(get_currency_precision(self.currency), 0)

	def test_compute_row_amount_missing_inputs_zero(self):
		row = frappe._dict(qty=5, valuation_rate=None)
		self.assertEqual(compute_row_amount(row, self.currency, rate_field="valuation_rate"), 0.0)

	def test_normalize_never_leaves_amount_empty_when_qty_and_rate(self):
		row = frappe._dict(
			idx=1,
			qty=2,
			valuation_rate=100.4,
			current_qty=1,
			current_valuation_rate=50.2,
			amount=None,
			current_amount=None,
		)
		normalize_stock_reconciliation_row(row, self.currency)
		self.assertIsNotNone(row.amount)
		self.assertIsNotNone(row.current_amount)
		self.assertIsNotNone(row.amount_difference)
		self.assertEqual(flt(row.amount), 201)
		self.assertEqual(flt(row.current_amount), 50)
		self.assertEqual(flt(row.amount_difference), 151)

	def test_opening_sr_rows_have_amounts_after_validate(self):
		item = ensure_test_item(self.company, prefix="IA-SR-ROW-UT")
		wh = get_warehouse(self.company)
		sr = _create_opening_sr(self.company, wh, item, 4, valuation_rate=999.99)
		frappe.db.commit()
		for row in sr.items:
			self.assertIsNotNone(row.amount)
			if flt(row.qty) and row.valuation_rate not in (None, ""):
				self.assertEqual(
					flt(row.amount),
					flt(compute_row_amount(row, self.currency, rate_field="valuation_rate")),
				)
		from erpnext_extensions.iran_accounting.domain.qty_rate_amount import (
			sum_stock_reconciliation_amount_difference,
		)

		self.assertEqual(flt(sr.difference_amount), sum_stock_reconciliation_amount_difference(sr))
