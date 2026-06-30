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
from erpnext_extensions.iran_accounting.rounding import amount_is_fractional, get_company_currency, round_row_amount
from erpnext_extensions.iran_accounting.stock_reconciliation_debug import _create_opening_sr


class TestSrGlConsistency(unittest.TestCase):
	def setUp(self):
		from erpnext_extensions.iran_accounting.integration.bootstrap import apply

		apply()
		frappe.set_user("Administrator")
		self.company = get_irr_company(None)
		self.warehouse = get_warehouse(self.company)
		self.currency = get_company_currency(self.company)

	def test_header_equals_amount_difference_sum(self):
		item = ensure_test_item(self.company, prefix="IA-SR-HDR-NET")
		sr = _create_opening_sr(self.company, self.warehouse, item, 3, valuation_rate=9877)
		frappe.db.commit()
		sr.reload()
		net = sum_stock_reconciliation_amount_difference(sr)
		self.assertEqual(flt(sr.difference_amount), net)
		self.assertEqual(flt(sr.difference_amount), 29631)

	def test_no_gross_header_used(self):
		doc = frappe.new_doc("Stock Reconciliation")
		doc.company = self.company
		doc.append(
			"items",
			{
				"qty": 10,
				"valuation_rate": 100,
				"current_qty": 5,
				"current_valuation_rate": 100,
			},
		)
		override_difference_amount(doc)
		gross = sum_stock_reconciliation_row_amounts(doc, self.currency)
		net = sum_stock_reconciliation_amount_difference(doc)
		self.assertEqual(flt(doc.difference_amount), net)
		self.assertNotEqual(flt(doc.difference_amount), gross)

	def test_gl_matches_sr(self):
		item = ensure_test_item(self.company, prefix="IA-SR-GL-MATCH")
		sr = _create_opening_sr(self.company, self.warehouse, item, 2, valuation_rate=1500.5)
		frappe.db.commit()
		chk = check_qty_rate_amount_consistency("Stock Reconciliation", sr.name, self.company)
		self.assertEqual(chk["status"], "PASS", chk.get("consistency_failures"))
		totals = chk["totals"]
		self.assertEqual(totals["header_vs_rows_residual"], 0)
		self.assertEqual(totals["difference_vs_gl_residual"], 0)
		self.assertEqual(totals["difference_vs_sle_residual"], 0)

	def test_irr_integer_only(self):
		self.assertEqual(round_row_amount(3, 9877, "IRR"), 29631)
		self.assertFalse(amount_is_fractional(29631, "IRR"))

	def test_known_voucher_net_header_if_submitted(self):
		for name in ("MAT-RECO-2026-00245", "MAT-RECO-2026-00187", "MAT-RECO-2026-00197"):
			if not frappe.db.exists("Stock Reconciliation", name):
				continue
			if frappe.db.get_value("Stock Reconciliation", name, "docstatus") != 1:
				continue
			doc = frappe.get_doc("Stock Reconciliation", name)
			override_difference_amount(doc)
			net = sum_stock_reconciliation_amount_difference(doc)
			chk = check_qty_rate_amount_consistency("Stock Reconciliation", name, self.company)
			self.assertEqual(flt(doc.difference_amount), net, name)
			self.assertEqual(chk["totals"]["header_vs_rows_residual"], 0, name)
