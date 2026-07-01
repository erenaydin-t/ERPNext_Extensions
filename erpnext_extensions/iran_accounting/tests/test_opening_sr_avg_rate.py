# Copyright (c) 2026, ERPNext Extensions contributors

from __future__ import annotations

import unittest

import frappe
from frappe.utils import flt

from erpnext_extensions.iran_accounting.domain.stock_ledger_deterministic import (
	irr_avg_rate_from_balance,
	resolve_irr_balance_avg_rate,
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


class TestOpeningSrAvgRateBalanceStock(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		from erpnext_extensions.iran_accounting.integration.bootstrap import apply

		apply()
		frappe.set_user("Administrator")
		cls.company = get_irr_company("ESPAD")
		enable_perpetual_inventory(cls.company)
		cls.wh = get_warehouse(cls.company)
		cls.frac_uom = fractional_uom()

	def _assert_sle_avg_rate(self, voucher_no: str, item_code: str | None = None):
		filters = {"voucher_type": "Stock Reconciliation", "voucher_no": voucher_no, "is_cancelled": 0}
		if item_code:
			filters["item_code"] = item_code
		sles = frappe.get_all(
			"Stock Ledger Entry",
			filters=filters,
			fields=["name", "item_code", "stock_value", "qty_after_transaction", "valuation_rate", "incoming_rate"],
		)
		self.assertTrue(sles, f"no SLE for {voucher_no}")
		for sle in sles:
			qty = flt(sle.qty_after_transaction)
			val = flt(sle.stock_value)
			exp = resolve_irr_balance_avg_rate(
				{
					"stock_value": val,
					"qty_after_transaction": qty,
					"incoming_rate": sle.get("incoming_rate"),
					"voucher_type": "Stock Reconciliation",
					"voucher_detail_no": frappe.db.get_value(
						"Stock Ledger Entry", sle.name, "voucher_detail_no"
					),
				},
				self.company,
			)
			if qty > 0 and val > 0 and exp > 0:
				self.assertGreater(
					flt(sle.valuation_rate),
					0,
					f"{sle.name} item={sle.item_code}: avg must not be zero when balance implies non-zero avg",
				)
			self.assertEqual(
				flt(sle.valuation_rate),
				exp,
				f"{sle.name} item={sle.item_code} val={val} qty={qty}",
			)

	def test_opening_new_item(self):
		item = ensure_test_item(self.company, "IA-AVG-NEW", stock_uom=self.frac_uom)
		sr = _create_opening_sr(self.company, self.wh, item, 10, valuation_rate=5000)
		frappe.db.commit()
		self._assert_sle_avg_rate(sr.name)

	def test_opening_existing_item_zero_prior_stock(self):
		item = ensure_test_item(self.company, "IA-AVG-ZERO-PRIOR", stock_uom=self.frac_uom)
		sr = _create_opening_sr(self.company, self.wh, item, 4, valuation_rate=2500)
		frappe.db.commit()
		self._assert_sle_avg_rate(sr.name)

	def test_opening_existing_item_with_prior_stock(self):
		item = ensure_test_item(self.company, "IA-AVG-PRIOR", stock_uom=self.frac_uom)
		submit_material_receipt(self.company, item, qty=8, rate=3000, warehouse=self.wh)
		sr = _create_opening_sr(self.company, self.wh, item, 12, valuation_rate=4500)
		frappe.db.commit()
		self._assert_sle_avg_rate(sr.name)

	def test_opening_fractional_qty_seven_decimals(self):
		item = ensure_test_item(self.company, "IA-AVG-FRAC", stock_uom=self.frac_uom)
		qty = 3.1415926
		rate = 9877
		sr = _create_opening_sr(self.company, self.wh, item, qty, valuation_rate=rate)
		frappe.db.commit()
		self._assert_sle_avg_rate(sr.name)

	def test_opening_multiple_rows(self):
		items = [
			("IA-AVG-M1", 5, 1111),
			("IA-AVG-M2", 2.5, 4444),
			("IA-AVG-M3", 0.0000007, 999_999),
		]
		sr = frappe.new_doc("Stock Reconciliation")
		sr.purpose = "Opening Stock"
		sr.company = self.company
		sr.posting_date = frappe.utils.today()
		sr.set_posting_time = 1
		sr.expense_account = (
			frappe.get_cached_value("Company", self.company, "temporary_opening_account")
			or frappe.db.get_value(
				"Account",
				{"company": self.company, "account_type": "Temporary", "is_group": 0},
				"name",
			)
		)
		sr.cost_center = frappe.get_cached_value("Company", self.company, "cost_center")
		sr.difference_account = sr.expense_account
		for code, qty, rate in items:
			item = ensure_test_item(self.company, code, stock_uom=self.frac_uom)
			sr.append(
				"items",
				{
					"item_code": item,
					"warehouse": self.wh,
					"qty": qty,
					"valuation_rate": rate,
					"uom": self.frac_uom,
					"stock_uom": self.frac_uom,
					"conversion_factor": 1,
					"reconcile_all_serial_batch": 1,
				},
			)
		sr.insert()
		sr.submit()
		frappe.db.commit()
		self._assert_sle_avg_rate(sr.name)

	def test_known_voucher_mat_reco_00282_if_present(self):
		name = "MAT-RECO-2026-00282"
		if not frappe.db.exists("Stock Reconciliation", name):
			self.skipTest(f"{name} not on site")
		if frappe.db.get_value("Stock Reconciliation", name, "docstatus") != 1:
			self.skipTest(f"{name} not submitted")
		from erpnext_extensions.iran_accounting.domain.repost_determinism import (
			reconcile_irr_after_repost,
		)

		reconcile_irr_after_repost("Stock Reconciliation", name, validate=False)
		for sle_name in frappe.get_all(
			"Stock Ledger Entry",
			filters={"voucher_type": "Stock Reconciliation", "voucher_no": name, "is_cancelled": 0},
			pluck="name",
		):
			sle = frappe.get_doc("Stock Ledger Entry", sle_name)
			from erpnext_extensions.iran_accounting.domain.stock_ledger_deterministic import (
				apply_irr_deterministic_sle_valuation,
			)

			apply_irr_deterministic_sle_valuation(sle, self.company)
			sle.db_update()
		frappe.db.commit()
		for item in ("17000039", "17300024"):
			if frappe.db.exists("Item", item):
				self._assert_sle_avg_rate(name, item_code=item)
