# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

import unittest

import frappe

from erpnext_extensions.iran_accounting.e2e_bootstrap import get_irr_company
from erpnext_extensions.consignment_stock.party import resolve_party_account, validate_consignment_party
from erpnext_extensions.consignment_stock.tests.helpers import (
	ensure_customer,
	ensure_module_ready,
	ensure_settings,
	ensure_supplier,
)


class TestConsignmentParty(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		ensure_module_ready()
		cls.company = get_irr_company("ESPAD")
		ensure_settings(cls.company)
		cls.supplier = ensure_supplier(cls.company)
		cls.customer = ensure_customer(cls.company)

	def test_supplier_resolves_payable(self):
		account = validate_consignment_party("Supplier", self.supplier, self.company)
		self.assertEqual(frappe.get_cached_value("Account", account, "account_type"), "Payable")

	def test_customer_resolves_receivable(self):
		account = validate_consignment_party("Customer", self.customer, self.company)
		self.assertEqual(frappe.get_cached_value("Account", account, "account_type"), "Receivable")

	def test_missing_party_throws(self):
		with self.assertRaises(frappe.ValidationError):
			validate_consignment_party("Supplier", None, self.company)

	def test_resolve_matches_get_party_account(self):
		a = resolve_party_account("Supplier", self.supplier, self.company)
		b = resolve_party_account("Customer", self.customer, self.company)
		self.assertTrue(a)
		self.assertTrue(b)
		self.assertNotEqual(a, b)
