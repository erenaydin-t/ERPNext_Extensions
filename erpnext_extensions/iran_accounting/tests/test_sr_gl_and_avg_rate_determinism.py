# Copyright (c) 2026, ERPNext Extensions contributors

from __future__ import annotations

import unittest

import frappe
from frappe.utils import flt

from erpnext_extensions.iran_accounting.domain.qty_rate_amount import (
	sum_stock_reconciliation_amount_difference,
	sum_stock_reconciliation_row_amounts,
)
from erpnext_extensions.iran_accounting.domain.stock_ledger_deterministic import irr_avg_rate_from_balance
from erpnext_extensions.iran_accounting.e2e_bootstrap import (
	enable_perpetual_inventory,
	ensure_test_item,
	get_irr_company,
	get_warehouse,
	submit_material_receipt,
	submit_stock_reconciliation_adjustment,
)
from erpnext_extensions.iran_accounting.qty_rate_consistency import check_qty_rate_amount_consistency
from erpnext_extensions.iran_accounting.stock_reconciliation_debug import _create_opening_sr
from erpnext_extensions.iran_accounting.validation import fetch_gl_rows, gl_debit_credit_totals


class TestSrGlAndAvgRateDeterminism(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		from erpnext_extensions.iran_accounting.integration.bootstrap import apply

		apply()
		frappe.set_user("Administrator")
		cls.company = get_irr_company("ESPAD")
		enable_perpetual_inventory(cls.company)
		cls.wh = get_warehouse(cls.company)

	def _assert_gl_exists_and_matches_rows(self, sr_name: str):
		frappe.db.commit()
		doc = frappe.get_doc("Stock Reconciliation", sr_name)
		net = sum_stock_reconciliation_amount_difference(doc)
		gross = sum_stock_reconciliation_row_amounts(doc)
		gl_rows = fetch_gl_rows("Stock Reconciliation", sr_name)
		self.assertTrue(gl_rows, f"no GL for {sr_name}")
		debit, credit = gl_debit_credit_totals(gl_rows)
		gl_mag = max(flt(debit), flt(credit))
		self.assertEqual(gl_mag, abs(net), f"net={net} gross={gross} gl={gl_mag}")
		chk = check_qty_rate_amount_consistency("Stock Reconciliation", sr_name, self.company)
		self.assertEqual(chk["status"], "PASS", chk)

	def test_opening_stock_gl_and_avg_rate(self):
		item = ensure_test_item(self.company, "IA-SR-GL-OPEN", stock_uom="Nos")
		sr = _create_opening_sr(self.company, self.wh, item, 6, valuation_rate=3000)
		self._assert_gl_exists_and_matches_rows(sr.name)
		sle = frappe.db.get_value(
			"Stock Ledger Entry",
			{"voucher_type": "Stock Reconciliation", "voucher_no": sr.name},
			["qty_after_transaction", "stock_value", "valuation_rate", "incoming_rate"],
			as_dict=True,
		)
		exp_avg = irr_avg_rate_from_balance(sle.stock_value, sle.qty_after_transaction, "IRR")
		self.assertEqual(flt(sle.valuation_rate), exp_avg)
		self.assertEqual(flt(sle.incoming_rate), 3000)

	def test_normal_reconciliation_gl(self):
		item = ensure_test_item(self.company, "IA-SR-GL-ADJ", stock_uom="Nos")
		submit_material_receipt(self.company, item, qty=10, rate=5000, warehouse=self.wh)
		sr = submit_stock_reconciliation_adjustment(self.company, item, qty=12, rate=5000, warehouse=self.wh)
		self._assert_gl_exists_and_matches_rows(sr.name)

	def test_opening_incoming_rate_equals_prior_avg(self):
		item = ensure_test_item(self.company, "IA-SR-GL-PRIOR", stock_uom="Nos")
		submit_material_receipt(self.company, item, qty=4, rate=2500, warehouse=self.wh)
		sr = submit_stock_reconciliation_adjustment(self.company, item, qty=6, rate=2500, warehouse=self.wh)
		frappe.db.commit()
		sle = frappe.db.get_value(
			"Stock Ledger Entry",
			{"voucher_type": "Stock Reconciliation", "voucher_no": sr.name},
			["incoming_rate", "valuation_rate", "qty_after_transaction", "stock_value"],
			as_dict=True,
		)
		self.assertEqual(flt(sle.incoming_rate), 2500)
		exp_avg = irr_avg_rate_from_balance(sle.stock_value, sle.qty_after_transaction, "IRR")
		self.assertEqual(flt(sle.valuation_rate), exp_avg)

	def test_known_voucher_has_gl_if_present(self):
		name = "MAT-RECO-2026-00262"
		if not frappe.db.exists("Stock Reconciliation", name):
			self.skipTest(f"{name} not on site")
		if frappe.db.get_value("Stock Reconciliation", name, "docstatus") != 1:
			self.skipTest(f"{name} not submitted")
		from erpnext_extensions.iran_accounting.domain.stock_reconciliation import (
			ensure_stock_reconciliation_gl_entries,
		)

		doc = frappe.get_doc("Stock Reconciliation", name)
		ensure_stock_reconciliation_gl_entries(doc)
		self._assert_gl_exists_and_matches_rows(name)
