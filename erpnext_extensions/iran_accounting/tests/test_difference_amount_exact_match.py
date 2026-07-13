# Copyright (c) 2026, ERPNext Extensions contributors

from __future__ import annotations

import unittest

import frappe
from frappe.utils import flt, nowtime, today

from erpnext_extensions.iran_accounting.domain.qty_rate_amount import (
	compute_final_difference_amount,
	sum_stock_reconciliation_amount_difference,
)
from erpnext_extensions.iran_accounting.e2e_bootstrap import ensure_test_item, get_irr_company, get_warehouse
from erpnext_extensions.iran_accounting.rounding import get_company_currency, round_currency
from erpnext_extensions.iran_accounting.stock_reconciliation_debug import _create_opening_sr


class TestDifferenceAmountExactMatch(unittest.TestCase):
	def setUp(self):
		from erpnext_extensions.iran_accounting.integration.bootstrap import apply

		apply()
		frappe.set_user("Administrator")
		self.company = get_irr_company(None)
		self.warehouse = get_warehouse(self.company)
		self.currency = get_company_currency(self.company)

	def _assert_opening_header(self, doc):
		doc.reload()
		from erpnext_extensions.iran_accounting.domain.qty_rate_amount import (
			sum_stock_reconciliation_amount_difference,
		)

		expected = sum_stock_reconciliation_amount_difference(doc)
		self.assertEqual(flt(doc.difference_amount), expected)

	def test_opening_fractional_rate_irr(self):
		item = ensure_test_item(self.company, prefix="IA-SR-EXACT-1")
		sr = _create_opening_sr(self.company, self.warehouse, item, 2, valuation_rate=333.33)
		frappe.db.commit()
		self._assert_opening_header(sr)

	def test_batch_row_exact_match(self):
		item = ensure_test_item(self.company, prefix="IA-SR-EXACT-B")
		frappe.db.set_value("Item", item, "has_batch_no", 1, update_modified=False)
		batch = frappe.get_doc(
			{"doctype": "Batch", "item": item, "batch_id": f"IA-EX-{frappe.generate_hash(length=6)}"}
		)
		batch.insert(ignore_permissions=True)
		sr = _create_opening_sr(
			self.company, self.warehouse, item, 4, valuation_rate=1250.75, batch_no=batch.name
		)
		frappe.db.commit()
		self._assert_opening_header(sr)

	def test_large_opening_sr_many_rows(self):
		"""Regression: header must equal Σ per-row rounded qty×rate (100+ lines)."""
		template = "MAT-RECO-2026-00174"
		if not frappe.db.exists("Stock Reconciliation", template):
			self.skipTest(f"template {template} missing")
		src = frappe.get_doc("Stock Reconciliation", template)
		sr = frappe.new_doc("Stock Reconciliation")
		sr.purpose = "Opening Stock"
		sr.company = src.company
		sr.posting_date = today()
		sr.posting_time = nowtime()
		sr.set_posting_time = 1
		sr.expense_account = src.expense_account
		sr.cost_center = src.cost_center
		sr.difference_account = src.expense_account
		for r in (src.items or [])[:105]:
			sr.append(
				"items",
				{
					"item_code": r.item_code,
					"warehouse": r.warehouse,
					"qty": flt(r.qty) + 1,
					"valuation_rate": flt(r.valuation_rate) + 1,
					"allow_zero_valuation_rate": r.allow_zero_valuation_rate or 0,
				},
			)
		compute_final_difference_amount(sr)
		self.assertGreaterEqual(len(sr.items), 100)
		expected = sum_stock_reconciliation_amount_difference(sr)
		self.assertEqual(flt(sr.difference_amount), expected)
