# Copyright (c) 2026, ERPNext Extensions contributors

from __future__ import annotations

import random
import unittest

import frappe
from erpnext.stock.doctype.stock_entry.stock_entry_utils import make_stock_entry
from frappe.utils import flt, random_string

from erpnext_extensions.iran_accounting.domain.currency import round_row_amount_financial
from erpnext_extensions.iran_accounting.domain.stock_entry_ledger_contract import (
	enforce_stock_entry_ledger_contract,
)
from erpnext_extensions.iran_accounting.e2e_bootstrap import (
	enable_perpetual_inventory,
	ensure_test_item,
	fractional_uom,
	get_irr_company,
	get_second_warehouse,
	get_warehouse,
	submit_material_receipt,
	submit_material_transfer,
)
from erpnext_extensions.iran_accounting.stock_gl_consistency import (
	assert_sle_gl_equal,
	assert_stock_entry_ledger_determinism,
)
from erpnext_extensions.iran_accounting.validation import voucher_db_flags


class TestStockSleGlConsistency(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		from erpnext_extensions.iran_accounting.integration.bootstrap import apply

		apply()
		frappe.set_user("Administrator")
		cls.company = get_irr_company("ESPAD")
		enable_perpetual_inventory(cls.company)
		cls.wh = get_warehouse(cls.company)
		cls.wh2 = get_second_warehouse(cls.company, cls.wh)
		cls.frac_uom = fractional_uom()

	def _assert_voucher(self, se_name: str):
		frappe.db.commit()
		contract = enforce_stock_entry_ledger_contract(se_name, self.company, raise_on_fail=True)
		self.assertEqual(contract["status"], "PASS", contract)
		det = assert_stock_entry_ledger_determinism(se_name, self.company)
		self.assertEqual(det["status"], "PASS", det)
		chk = assert_sle_gl_equal("Stock Entry", se_name, self.company)
		self.assertEqual(chk["status"], "PASS", chk)
		flags = voucher_db_flags("Stock Entry", se_name, self.company)
		self.assertTrue(flags["gl_ok"], flags)
		self.assertTrue(flags["sle_ok"], flags)

	def test_material_receipt_fractional_qty(self):
		item = ensure_test_item(self.company, "IA-SLEGL-MR", stock_uom=self.frac_uom)
		qty = 1.2345678
		rate = 9877
		se = make_stock_entry(
			item_code=item,
			qty=qty,
			target=self.wh,
			rate=rate,
			company=self.company,
			purpose="Material Receipt",
		)
		se.submit()
		self._assert_voucher(se.name)
		se.reload()
		row = se.items[0]
		# ERPNext owns amount via transfer_qty × basic_rate (+ capitalized costs).
		transfer_qty = row.transfer_qty if row.transfer_qty not in (None, "") else row.qty
		exp = round_row_amount_financial(transfer_qty, row.basic_rate, "IRR")
		self.assertEqual(flt(row.basic_amount), exp)
		self.assertEqual(
			flt(row.amount),
			flt(row.basic_amount) + flt(row.additional_cost) + flt(row.landed_cost_voucher_amount),
		)

	def test_material_issue_fractional_qty(self):
		item = ensure_test_item(self.company, "IA-SLEGL-MI", stock_uom=self.frac_uom)
		submit_material_receipt(self.company, item, qty=10, rate=5000, warehouse=self.wh)
		qty = 2.7654321
		rate = 5000
		se = make_stock_entry(
			item_code=item,
			qty=qty,
			source=self.wh,
			rate=rate,
			company=self.company,
			purpose="Material Issue",
		)
		se.submit()
		self._assert_voucher(se.name)

	def test_material_transfer_fractional_qty(self):
		item = ensure_test_item(self.company, "IA-SLEGL-MT", stock_uom=self.frac_uom)
		submit_material_receipt(self.company, item, qty=20, rate=3333, warehouse=self.wh)
		qty = 3.1415926
		se = submit_material_transfer(self.company, item, qty, self.wh, self.wh2)
		se.submit()
		self._assert_voucher(se.name)

	def test_mixed_multi_item_material_receipt(self):
		items = [
			("IA-SLEGL-MIX-A", 1.1111111, 12345),
			("IA-SLEGL-MIX-B", 2.2222222, 67890),
			("IA-SLEGL-MIX-C", 0.1234567, 999_999),
		]
		se = frappe.new_doc("Stock Entry")
		se.stock_entry_type = "Material Receipt"
		se.purpose = "Material Receipt"
		se.company = self.company
		se.set_stock_entry_type()
		for code, qty, rate in items:
			item = ensure_test_item(self.company, code, stock_uom=self.frac_uom)
			se.append(
				"items",
				{
					"item_code": item,
					"qty": qty,
					"transfer_qty": qty,
					"basic_rate": rate,
					"t_warehouse": self.wh,
					"uom": self.frac_uom,
					"stock_uom": self.frac_uom,
					"conversion_factor": 1,
				},
			)
		se.insert()
		se.submit()
		doc = frappe.get_doc("Stock Entry", se.name)
		expected = 0.0
		for row in doc.items:
			tq = row.transfer_qty if row.transfer_qty not in (None, "") else row.qty
			expected += round_row_amount_financial(tq, row.basic_rate, "IRR")
		self.assertEqual(flt(doc.total_incoming_value), expected)
		self._assert_voucher(se.name)

	def test_random_stress_sle_gl_mixed(self):
		random.seed(20260701)
		purposes = ("Material Receipt", "Material Issue", "Material Transfer")
		for i in range(100):
			item = ensure_test_item(
				self.company, f"IA-SLEGL-R{i}-{random_string(4)}", stock_uom=self.frac_uom
			)
			rate = random.randint(1, 999_999)
			qty = round(random.uniform(0.0000001, 9999.9999999), 7)
			submit_material_receipt(self.company, item, qty=max(qty, 1) * 10, rate=rate, warehouse=self.wh)
			purpose = random.choice(purposes)
			if purpose == "Material Receipt":
				se = make_stock_entry(
					item_code=item,
					qty=qty,
					target=self.wh,
					rate=rate,
					company=self.company,
					purpose=purpose,
				)
			elif purpose == "Material Issue":
				se = make_stock_entry(
					item_code=item,
					qty=min(qty, 5),
					source=self.wh,
					rate=rate,
					company=self.company,
					purpose=purpose,
				)
			else:
				se = make_stock_entry(
					item_code=item,
					qty=min(qty, 5),
					source=self.wh,
					target=self.wh2,
					company=self.company,
					purpose=purpose,
				)
			se.submit()
			self._assert_voucher(se.name)
