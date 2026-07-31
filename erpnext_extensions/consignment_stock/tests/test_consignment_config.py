# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

import unittest

import frappe
from frappe.utils import random_string

from erpnext_extensions.iran_accounting.e2e_bootstrap import get_irr_company
from erpnext_extensions.consignment_stock.constants import F_IS_RECEIPT, F_IS_RETURN
from erpnext_extensions.consignment_stock.tests.helpers import (
	ensure_consignment_accounts,
	ensure_module_ready,
	ensure_settings,
	ensure_stock_entry_types,
)


class TestConsignmentConfig(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		ensure_module_ready()
		cls.company = get_irr_company("ESPAD")
		cls.settings_name = ensure_settings(cls.company)
		cls.types = ensure_stock_entry_types()

	def test_settings_accounts_valid(self):
		doc = frappe.get_doc("Consignment Stock Settings", self.settings_name)
		self.assertTrue(doc.consignment_inventory_account)
		self.assertTrue(doc.consignment_temporary_clearing_account)
		self.assertTrue(doc.consignment_valuation_difference_account)

	def test_group_account_rejected(self):
		accounts = ensure_consignment_accounts(self.company)
		doc = frappe.copy_doc(frappe.get_doc("Consignment Stock Settings", self.settings_name))
		doc.name = None
		doc.company = f"{self.company}-X-{random_string(3)}"
		# Use real company but force group account
		doc = frappe.get_doc("Consignment Stock Settings", self.settings_name)
		group = frappe.db.get_value(
			"Account", {"company": self.company, "is_group": 1}, "name", order_by="lft asc"
		)
		doc.consignment_temporary_clearing_account = group
		with self.assertRaises(frappe.ValidationError):
			doc.validate()
		# restore
		doc.reload()
		doc.consignment_temporary_clearing_account = accounts["temporary"]
		doc.save(ignore_permissions=True)

	def test_stock_entry_type_flags(self):
		receipt = frappe.get_doc("Stock Entry Type", self.types["receipt"])
		self.assertEqual(receipt.purpose, "Material Receipt")
		self.assertTrue(receipt.get(F_IS_RECEIPT))
		ret = frappe.get_doc("Stock Entry Type", self.types["return"])
		self.assertEqual(ret.purpose, "Material Issue")
		self.assertTrue(ret.get(F_IS_RETURN))

	def test_incompatible_type_flags(self):
		doc = frappe.get_doc("Stock Entry Type", self.types["receipt"])
		doc.set(F_IS_RETURN, 1)
		with self.assertRaises(frappe.ValidationError):
			doc.save()
		doc.reload()
