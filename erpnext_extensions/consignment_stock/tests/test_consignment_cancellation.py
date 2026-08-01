# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

import unittest

import frappe

from erpnext_extensions.iran_accounting.e2e_bootstrap import ensure_test_item, get_irr_company
from erpnext_extensions.consignment_stock.api import (
	create_consignment_recognition_entry,
	create_consignment_return_settlement,
)
from erpnext_extensions.consignment_stock.tests.helpers import (
	ensure_module_ready,
	ensure_settings,
	ensure_stock_entry_types,
	ensure_supplier,
	make_consignment_receipt,
	make_consignment_return,
)


class TestConsignmentCancellation(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		ensure_module_ready()
		cls.company = get_irr_company("ESPAD")
		cls.settings = frappe.get_doc("Consignment Stock Settings", ensure_settings(cls.company))
		cls.types = ensure_stock_entry_types()
		cls.supplier = ensure_supplier(cls.company)
		cls.wh = cls.settings.default_consignment_warehouse

	def test_cancel_receipt_without_recognition_ok(self):
		se = make_consignment_receipt(
			company=self.company,
			warehouse=self.wh,
			item_code=ensure_test_item(self.company, "CS-CXL-R"),
			qty=2,
			rate=1000,
			party_type="Supplier",
			party=self.supplier,
			stock_entry_type=self.types["receipt"],
		)
		se.cancel()
		self.assertEqual(se.docstatus, 2)

	def test_cancel_receipt_blocked_after_submitted_recognition(self):
		se = make_consignment_receipt(
			company=self.company,
			warehouse=self.wh,
			item_code=ensure_test_item(self.company, "CS-CXL-RR"),
			qty=2,
			rate=1000,
			party_type="Supplier",
			party=self.supplier,
			stock_entry_type=self.types["receipt"],
		)
		je_name = create_consignment_recognition_entry(se.name)["journal_entry"]
		frappe.get_doc("Journal Entry", je_name).submit()
		se.reload()
		with self.assertRaises(frappe.ValidationError):
			se.cancel()

	def test_cancel_je_clears_link(self):
		se = make_consignment_receipt(
			company=self.company,
			warehouse=self.wh,
			item_code=ensure_test_item(self.company, "CS-CXL-JE"),
			qty=2,
			rate=1000,
			party_type="Supplier",
			party=self.supplier,
			stock_entry_type=self.types["receipt"],
		)
		je_name = create_consignment_recognition_entry(se.name)["journal_entry"]
		je = frappe.get_doc("Journal Entry", je_name)
		je.submit()
		je.cancel()
		se.reload()
		self.assertFalse(se.get("custom_consignment_recognition_je"))

	def test_cancel_return_blocked_after_settlement(self):
		item = ensure_test_item(self.company, "CS-CXL-SET")
		receipt = make_consignment_receipt(
			company=self.company,
			warehouse=self.wh,
			item_code=item,
			qty=4,
			rate=1000,
			party_type="Supplier",
			party=self.supplier,
			stock_entry_type=self.types["receipt"],
		)
		je = create_consignment_recognition_entry(receipt.name)["journal_entry"]
		frappe.get_doc("Journal Entry", je).submit()
		ret = make_consignment_return(
			company=self.company,
			warehouse=self.wh,
			item_code=item,
			qty=4,
			party_type="Supplier",
			party=self.supplier,
			stock_entry_type=self.types["return"],
			receipt_name=receipt.name,
			receipt_detail=receipt.items[0].name,
		)
		sje = create_consignment_return_settlement(ret.name)["journal_entry"]
		frappe.get_doc("Journal Entry", sje).submit()
		ret.reload()
		with self.assertRaises(frappe.ValidationError):
			ret.cancel()
