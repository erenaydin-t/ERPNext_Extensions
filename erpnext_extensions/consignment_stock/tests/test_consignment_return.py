# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

import unittest

import frappe
from frappe.utils import flt

from erpnext_extensions.iran_accounting.e2e_bootstrap import ensure_test_item, get_irr_company
from erpnext_extensions.consignment_stock.api import create_consignment_recognition_entry
from erpnext_extensions.consignment_stock.tests.helpers import (
	ensure_module_ready,
	ensure_settings,
	ensure_stock_entry_types,
	ensure_supplier,
	gl_rows_for,
	make_consignment_receipt,
	make_consignment_return,
)


class TestConsignmentReturn(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		ensure_module_ready()
		cls.company = get_irr_company("ESPAD")
		cls.settings = frappe.get_doc("Consignment Stock Settings", ensure_settings(cls.company))
		cls.types = ensure_stock_entry_types()
		cls.supplier = ensure_supplier(cls.company)
		cls.wh = cls.settings.default_consignment_warehouse

	def _recognized_receipt(self, prefix: str, qty=10, rate=1000):
		item = ensure_test_item(self.company, prefix)
		se = make_consignment_receipt(
			company=self.company,
			warehouse=self.wh,
			item_code=item,
			qty=qty,
			rate=rate,
			party_type="Supplier",
			party=self.supplier,
			stock_entry_type=self.types["receipt"],
		)
		out = create_consignment_recognition_entry(se.name)
		frappe.get_doc("Journal Entry", out["journal_entry"]).submit()
		se.reload()
		return se, item

	def test_return_blocked_without_recognition(self):
		item = ensure_test_item(self.company, "CS-RET-L1")
		se = make_consignment_receipt(
			company=self.company,
			warehouse=self.wh,
			item_code=item,
			qty=10,
			rate=1000,
			party_type="Supplier",
			party=self.supplier,
			stock_entry_type=self.types["receipt"],
		)
		with self.assertRaises(frappe.ValidationError):
			make_consignment_return(
				company=self.company,
				warehouse=self.wh,
				item_code=item,
				qty=5,
				party_type="Supplier",
				party=self.supplier,
				stock_entry_type=self.types["return"],
				receipt_name=se.name,
				receipt_detail=se.items[0].name,
				submit=False,
			)

	def test_return_blocked_when_recognition_draft(self):
		item = ensure_test_item(self.company, "CS-RET-DR")
		se = make_consignment_receipt(
			company=self.company,
			warehouse=self.wh,
			item_code=item,
			qty=8,
			rate=1000,
			party_type="Supplier",
			party=self.supplier,
			stock_entry_type=self.types["receipt"],
		)
		create_consignment_recognition_entry(se.name)
		with self.assertRaises(frappe.ValidationError):
			make_consignment_return(
				company=self.company,
				warehouse=self.wh,
				item_code=item,
				qty=3,
				party_type="Supplier",
				party=self.supplier,
				stock_entry_type=self.types["return"],
				receipt_name=se.name,
				receipt_detail=se.items[0].name,
				submit=False,
			)

	def test_full_return_gl(self):
		receipt, item = self._recognized_receipt("CS-RET-FULL", qty=10, rate=1000)
		ret = make_consignment_return(
			company=self.company,
			warehouse=self.wh,
			item_code=item,
			qty=10,
			party_type="Supplier",
			party=self.supplier,
			stock_entry_type=self.types["return"],
			receipt_name=receipt.name,
			receipt_detail=receipt.items[0].name,
		)
		self.assertEqual(
			ret.items[0].expense_account, self.settings.consignment_temporary_clearing_account
		)
		gl = gl_rows_for("Stock Entry", ret.name)
		temp = self.settings.consignment_temporary_clearing_account
		inv = self.settings.consignment_inventory_account
		debit_temp = sum(flt(r.debit) for r in gl if r.account == temp)
		credit_inv = sum(flt(r.credit) for r in gl if r.account == inv)
		self.assertEqual(debit_temp, credit_inv)
		self.assertGreater(debit_temp, 0)

	def test_over_return_blocked(self):
		receipt, item = self._recognized_receipt("CS-RET-OV", qty=5, rate=1000)
		with self.assertRaises(frappe.ValidationError):
			make_consignment_return(
				company=self.company,
				warehouse=self.wh,
				item_code=item,
				qty=6,
				party_type="Supplier",
				party=self.supplier,
				stock_entry_type=self.types["return"],
				receipt_name=receipt.name,
				receipt_detail=receipt.items[0].name,
				submit=False,
			)

	def test_additional_costs_blocked_on_return(self):
		"""before_validate rejects additional_costs before ERPNext Issue clearing."""
		receipt, item = self._recognized_receipt("CS-RET-AC", qty=5, rate=1000)
		ret = make_consignment_return(
			company=self.company,
			warehouse=self.wh,
			item_code=item,
			qty=2,
			party_type="Supplier",
			party=self.supplier,
			stock_entry_type=self.types["return"],
			receipt_name=receipt.name,
			receipt_detail=receipt.items[0].name,
			submit=False,
		)
		ret.reload()
		ret.append(
			"additional_costs",
			{
				"expense_account": self.settings.consignment_valuation_difference_account,
				"description": "x",
				"amount": 10,
			},
		)
		with self.assertRaises(frappe.ValidationError):
			ret.save()
