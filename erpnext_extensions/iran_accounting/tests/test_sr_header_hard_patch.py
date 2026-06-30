# Copyright (c) 2026, ERPNext Extensions contributors

from __future__ import annotations

import unittest

import frappe
from frappe.utils import flt

from erpnext_extensions.iran_accounting.domain.qty_rate_amount import (
	override_difference_amount,
	sum_stock_reconciliation_amount_difference,
	sum_stock_reconciliation_row_amounts,
)
from erpnext_extensions.iran_accounting.e2e_bootstrap import ensure_test_item, get_irr_company, get_warehouse
from erpnext_extensions.iran_accounting.qty_rate_consistency import check_qty_rate_amount_consistency
from erpnext_extensions.iran_accounting.stock_reconciliation_debug import _create_opening_sr


class TestSrHeaderHardPatch(unittest.TestCase):
	def setUp(self):
		from erpnext_extensions.iran_accounting.integration.bootstrap import apply

		apply()
		frappe.set_user("Administrator")
		self.company = get_irr_company(None)
		self.warehouse = get_warehouse(self.company)

	def test_erpnext_set_total_qty_and_amount_is_patched(self):
		from erpnext.stock.doctype.stock_reconciliation.stock_reconciliation import StockReconciliation

		self.assertTrue(getattr(StockReconciliation, "_iran_patched_set_total", False))

	def test_sr_header_equals_sum_amount_difference(self):
		item = ensure_test_item(self.company, prefix="IA-HARD-HDR")
		sr = _create_opening_sr(self.company, self.warehouse, item, 3, valuation_rate=9877)
		frappe.db.commit()
		sr.reload()
		self.assertEqual(flt(sr.difference_amount), sum_stock_reconciliation_amount_difference(sr))

	def test_no_opening_stock_override_logic(self):
		doc = frappe.new_doc("Stock Reconciliation")
		doc.company = self.company
		doc.purpose = "Opening Stock"
		doc.append("items", {"qty": 2, "valuation_rate": 100, "current_qty": 1, "current_valuation_rate": 100})
		override_difference_amount(doc)
		self.assertEqual(flt(doc.difference_amount), sum_stock_reconciliation_amount_difference(doc))

	def test_no_erpnext_header_recompute_effect(self):
		from erpnext.stock.doctype.stock_reconciliation.stock_reconciliation import StockReconciliation

		doc = frappe.new_doc("Stock Reconciliation")
		doc.company = self.company
		doc.difference_amount = 999999999
		doc.append("items", {"qty": 1, "valuation_rate": 100, "current_qty": 0, "current_valuation_rate": 0})
		StockReconciliation.set_total_qty_and_amount(doc)
		self.assertEqual(flt(doc.difference_amount), 100)
		self.assertNotEqual(flt(doc.difference_amount), 999999999)

	def test_ir_reconciliation_production_vouchers_consistency(self):
		for name in ("MAT-RECO-2026-00248", "MAT-RECO-2026-00245", "MAT-RECO-2026-00187", "MAT-RECO-2026-00197"):
			if not frappe.db.exists("Stock Reconciliation", name):
				continue
			if frappe.db.get_value("Stock Reconciliation", name, "docstatus") != 1:
				continue
			doc = frappe.get_doc("Stock Reconciliation", name)
			override_difference_amount(doc)
			self.assertEqual(
				flt(doc.difference_amount),
				sum_stock_reconciliation_amount_difference(doc),
				msg=name,
			)
			chk = check_qty_rate_amount_consistency("Stock Reconciliation", name, self.company)
			self.assertEqual(chk["totals"]["header_vs_rows_residual"], 0, msg=name)
			gross = sum_stock_reconciliation_row_amounts(doc)
			if gross != flt(doc.difference_amount):
				self.assertNotEqual(gross, flt(doc.difference_amount))
