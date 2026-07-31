# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

import unittest

import frappe
from frappe.utils import flt

from erpnext_extensions.iran_accounting.e2e_bootstrap import ensure_test_item, get_irr_company
from erpnext_extensions.consignment_stock.constants import F_IS_RECEIPT
from erpnext_extensions.consignment_stock.tests.helpers import (
	ensure_module_ready,
	ensure_settings,
	ensure_stock_entry_types,
	ensure_supplier,
	gl_rows_for,
	make_consignment_receipt,
)


class TestConsignmentReceipt(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		ensure_module_ready()
		cls.company = get_irr_company("ESPAD")
		cls.settings = frappe.get_doc("Consignment Stock Settings", ensure_settings(cls.company))
		cls.types = ensure_stock_entry_types()
		cls.supplier = ensure_supplier(cls.company)
		cls.wh = cls.settings.default_consignment_warehouse
		cls.item = ensure_test_item(cls.company, "CS-RCV")

	def test_single_item_receipt_gl(self):
		se = make_consignment_receipt(
			company=self.company,
			warehouse=self.wh,
			item_code=self.item,
			qty=10,
			rate=1000,
			party_type="Supplier",
			party=self.supplier,
			stock_entry_type=self.types["receipt"],
		)
		self.assertEqual(cint_flag(se.get(F_IS_RECEIPT)), 1)
		self.assertEqual(flt(se.items[0].basic_rate), 1000)
		self.assertEqual(se.items[0].expense_account, self.settings.consignment_temporary_clearing_account)

		gl = gl_rows_for("Stock Entry", se.name)
		inv = self.settings.consignment_inventory_account
		temp = self.settings.consignment_temporary_clearing_account
		debit_inv = sum(flt(r.debit) for r in gl if r.account == inv)
		credit_temp = sum(flt(r.credit) for r in gl if r.account == temp)
		self.assertEqual(debit_inv, 10000)
		self.assertEqual(credit_temp, 10000)

	def test_missing_rate_throws(self):
		with self.assertRaises(frappe.ValidationError):
			make_consignment_receipt(
				company=self.company,
				warehouse=self.wh,
				item_code=ensure_test_item(self.company, "CS-RCV0"),
				qty=5,
				rate=0,
				party_type="Supplier",
				party=self.supplier,
				stock_entry_type=self.types["receipt"],
				submit=False,
			)

	def test_additional_costs_blocked(self):
		se = make_consignment_receipt(
			company=self.company,
			warehouse=self.wh,
			item_code=ensure_test_item(self.company, "CS-RCV-AC"),
			qty=2,
			rate=500,
			party_type="Supplier",
			party=self.supplier,
			stock_entry_type=self.types["receipt"],
			submit=False,
		)
		expense = self.settings.consignment_valuation_difference_account
		se.append(
			"additional_costs",
			{"expense_account": expense, "description": "freight", "amount": 100},
		)
		with self.assertRaises(frappe.ValidationError):
			se.save()


def cint_flag(v):
	from frappe.utils import cint

	return cint(v)
