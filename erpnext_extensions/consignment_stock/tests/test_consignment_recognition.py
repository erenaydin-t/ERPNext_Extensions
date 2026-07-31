# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

import unittest

import frappe
from frappe.utils import flt

from erpnext_extensions.iran_accounting.e2e_bootstrap import ensure_test_item, get_irr_company
from erpnext_extensions.consignment_stock.api import create_consignment_recognition_entry
from erpnext_extensions.consignment_stock.constants import F_RECOGNITION_JE, JE_ROLE_RECOGNITION
from erpnext_extensions.consignment_stock.tests.helpers import (
	ensure_customer,
	ensure_module_ready,
	ensure_settings,
	ensure_stock_entry_types,
	ensure_supplier,
	gl_rows_for,
	make_consignment_receipt,
)


class TestConsignmentRecognition(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		ensure_module_ready()
		cls.company = get_irr_company("ESPAD")
		cls.settings = frappe.get_doc("Consignment Stock Settings", ensure_settings(cls.company))
		cls.types = ensure_stock_entry_types()
		cls.supplier = ensure_supplier(cls.company)
		cls.customer = ensure_customer(cls.company)
		cls.wh = cls.settings.default_consignment_warehouse

	def test_recognition_draft_and_directions_supplier(self):
		se = make_consignment_receipt(
			company=self.company,
			warehouse=self.wh,
			item_code=ensure_test_item(self.company, "CS-REC-S"),
			qty=10,
			rate=1000,
			party_type="Supplier",
			party=self.supplier,
			stock_entry_type=self.types["receipt"],
		)
		out = create_consignment_recognition_entry(se.name)
		je = frappe.get_doc("Journal Entry", out["journal_entry"])
		self.assertEqual(je.docstatus, 0)
		self.assertEqual(je.get("custom_consignment_je_role"), JE_ROLE_RECOGNITION)
		se.reload()
		self.assertEqual(se.get(F_RECOGNITION_JE), je.name)

		temp = self.settings.consignment_temporary_clearing_account
		self.assertEqual(flt(je.accounts[0].debit_in_account_currency), 10000)
		self.assertEqual(je.accounts[0].account, temp)
		self.assertEqual(flt(je.accounts[1].credit_in_account_currency), 10000)
		self.assertEqual(je.accounts[1].party_type, "Supplier")
		self.assertEqual(je.accounts[1].party, self.supplier)
		# Party lines must not reference Stock Entry (Payment Ledger would block SE cancel)
		self.assertFalse(je.accounts[1].reference_type)
		self.assertIn(se.name, je.accounts[0].user_remark or "")

		je.submit()
		# no GL until submit — after submit
		gl = gl_rows_for("Journal Entry", je.name)
		self.assertTrue(gl)

	def test_duplicate_recognition_blocked(self):
		se = make_consignment_receipt(
			company=self.company,
			warehouse=self.wh,
			item_code=ensure_test_item(self.company, "CS-REC-D"),
			qty=5,
			rate=2000,
			party_type="Supplier",
			party=self.supplier,
			stock_entry_type=self.types["receipt"],
		)
		create_consignment_recognition_entry(se.name)
		with self.assertRaises(frappe.ValidationError):
			create_consignment_recognition_entry(se.name)

	def test_customer_recognition(self):
		se = make_consignment_receipt(
			company=self.company,
			warehouse=self.wh,
			item_code=ensure_test_item(self.company, "CS-REC-C"),
			qty=4,
			rate=2500,
			party_type="Customer",
			party=self.customer,
			stock_entry_type=self.types["receipt"],
		)
		out = create_consignment_recognition_entry(se.name)
		je = frappe.get_doc("Journal Entry", out["journal_entry"])
		self.assertEqual(je.accounts[1].party_type, "Customer")
		self.assertEqual(
			frappe.get_cached_value("Account", je.accounts[1].account, "account_type"),
			"Receivable",
		)
