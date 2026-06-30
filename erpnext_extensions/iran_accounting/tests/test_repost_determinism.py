# Copyright (c) 2026, ERPNext Extensions contributors

from __future__ import annotations

import unittest

import frappe
from frappe.utils import flt

from erpnext_extensions.iran_accounting.domain.repost_determinism import (
	reconcile_irr_after_repost,
	snapshot_stock_reconciliation_determinism,
)
from erpnext_extensions.iran_accounting.e2e_bootstrap import (
	enable_perpetual_inventory,
	ensure_test_item,
	fractional_uom,
	get_irr_company,
	get_warehouse,
	submit_material_receipt,
)
from erpnext_extensions.iran_accounting.stock_reconciliation_debug import _create_opening_sr


class TestRepostItemDoesNotBreakDeterminism(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		from erpnext_extensions.iran_accounting.integration.bootstrap import apply

		apply()
		frappe.set_user("Administrator")
		cls.company = get_irr_company("ESPAD")
		enable_perpetual_inventory(cls.company)
		cls.wh = get_warehouse(cls.company)
		cls.frac_uom = fractional_uom()

	def _run_riv_repost(self, voucher_type: str, voucher_no: str):
		if not frappe.db.exists("DocType", "Repost Item Valuation"):
			self.skipTest("Repost Item Valuation not installed")
		from erpnext.stock.doctype.repost_item_valuation.repost_item_valuation import repost

		riv = frappe.new_doc("Repost Item Valuation")
		riv.company = self.company
		riv.voucher_type = voucher_type
		riv.voucher_no = voucher_no
		riv.based_on = "Transaction"
		riv.repost_only_accounting_ledgers = 0
		riv.flags.ignore_permissions = True
		riv.insert(ignore_permissions=True)
		repost(riv)
		frappe.db.commit()

	def test_repost_item_does_not_break_determinism(self):
		item = ensure_test_item(self.company, "IA-REPOST-SR", stock_uom=self.frac_uom)
		qty = 3.1415926
		rate = 8765
		sr = _create_opening_sr(self.company, self.wh, item, qty, valuation_rate=rate)
		frappe.db.commit()

		before = snapshot_stock_reconciliation_determinism(sr.name, self.company)
		self._run_riv_repost("Stock Reconciliation", sr.name)
		reconcile_irr_after_repost("Stock Reconciliation", sr.name, self.company)
		after = snapshot_stock_reconciliation_determinism(sr.name, self.company)

		self.assertEqual(after["difference_amount"], before["difference_amount"])
		self.assertEqual(after["net_row_movement"], before["net_row_movement"])
		self.assertEqual(after["gl_magnitude"], before["gl_magnitude"])
		self.assertEqual(len(after["sles"]), len(before["sles"]))

		for b, a in zip(before["sles"], after["sles"], strict=True):
			self.assertEqual(flt(a["stock_value_difference"]), flt(b["stock_value_difference"]))
			self.assertEqual(flt(a["valuation_rate"]), flt(b["valuation_rate"]))
			self.assertEqual(flt(a["valuation_rate"]), flt(a["expected_avg"]))
			self.assertEqual(flt(a["incoming_rate"]), flt(b["incoming_rate"]))

	def test_repost_after_prior_stock_keeps_incoming_avg(self):
		item = ensure_test_item(self.company, "IA-REPOST-SR2", stock_uom=self.frac_uom)
		submit_material_receipt(self.company, item, qty=5, rate=4000, warehouse=self.wh)
		qty = 1.7654321
		sr = frappe.new_doc("Stock Reconciliation")
		sr.company = self.company
		sr.purpose = "Stock Reconciliation"
		sr.expense_account = frappe.get_cached_value("Company", self.company, "stock_adjustment_account")
		sr.cost_center = frappe.get_cached_value("Company", self.company, "cost_center")
		sr.append(
			"items",
			{
				"item_code": item,
				"warehouse": self.wh,
				"qty": qty + 5,
				"valuation_rate": 4000,
				"uom": self.frac_uom,
				"stock_uom": self.frac_uom,
				"conversion_factor": 1,
			},
		)
		sr.insert()
		sr.submit()
		frappe.db.commit()

		before = snapshot_stock_reconciliation_determinism(sr.name, self.company)
		self._run_riv_repost("Stock Reconciliation", sr.name)
		after = snapshot_stock_reconciliation_determinism(sr.name, self.company)
		self.assertEqual(after["difference_amount"], before["difference_amount"])
		self.assertEqual(after["gl_magnitude"], before["gl_magnitude"])
