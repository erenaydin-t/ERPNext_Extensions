# Copyright (c) 2026, ERPNext Extensions contributors

from __future__ import annotations

import unittest

import frappe

from erpnext_extensions.iran_accounting.e2e_bootstrap import (
	ensure_test_item,
	get_irr_company,
	get_warehouse,
	submit_opening_stock_reconciliation,
)


class TestOpeningStockReconciliation(unittest.TestCase):
	def setUp(self):
		import erpnext_extensions.iran_accounting  # noqa: F401

		frappe.set_user("Administrator")
		self.company = get_irr_company(None)
		self.warehouse = get_warehouse(self.company)

	def test_opening_stock_non_batch_sle_and_bin(self):
		item = ensure_test_item(self.company, prefix="IA-TEST-SR-UT")
		sr = submit_opening_stock_reconciliation(self.company, item, 5, 1234.567, self.warehouse)
		frappe.db.commit()
		sle = frappe.db.get_value(
			"Stock Ledger Entry",
			{"voucher_type": "Stock Reconciliation", "voucher_no": sr.name, "item_code": item},
			["qty_after_transaction", "incoming_rate", "valuation_rate", "stock_value"],
			as_dict=True,
		)
		bin_row = frappe.db.get_value(
			"Bin",
			{"item_code": item, "warehouse": self.warehouse},
			["actual_qty", "valuation_rate", "stock_value"],
			as_dict=True,
		)
		self.assertEqual(sle.qty_after_transaction, 5)
		self.assertEqual(sle.valuation_rate, 1235)
		self.assertEqual(sle.incoming_rate, 1235)
		self.assertEqual(sle.stock_value, 6175)
		self.assertEqual(bin_row.actual_qty, 5)
		self.assertEqual(bin_row.valuation_rate, 1235)
		self.assertEqual(bin_row.stock_value, 6175)
