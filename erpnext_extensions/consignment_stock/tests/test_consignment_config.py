# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

import unittest

import frappe

from erpnext_extensions.iran_accounting.e2e_bootstrap import get_irr_company
from erpnext_extensions.consignment_stock.constants import F_IS_RECEIPT, F_IS_RETURN
from erpnext_extensions.consignment_stock.tests.helpers import (
	ensure_consignment_accounts,
	ensure_module_ready,
	ensure_settings,
	ensure_stock_entry_types,
)


OBSOLETE_SETTINGS_FIELDS = (
	"consignment_inventory_account",
	"default_cost_center",
	"default_finance_book",
)

APPROVED_SETTINGS_FIELDS = (
	"company",
	"consignment_temporary_clearing_account",
	"consignment_valuation_difference_account",
	"default_consignment_warehouse",
	"allow_zero_receipt_rate",
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
		self.assertTrue(doc.consignment_temporary_clearing_account)
		self.assertTrue(doc.consignment_valuation_difference_account)
		self.assertTrue(doc.default_consignment_warehouse)

	def test_obsolete_settings_fields_absent(self):
		meta = frappe.get_meta("Consignment Stock Settings")
		fieldnames = {f.fieldname for f in meta.fields}
		for fn in OBSOLETE_SETTINGS_FIELDS:
			self.assertNotIn(fn, fieldnames)
		for fn in APPROVED_SETTINGS_FIELDS:
			self.assertIn(fn, fieldnames)

	def test_group_account_rejected(self):
		accounts = ensure_consignment_accounts(self.company)
		doc = frappe.get_doc("Consignment Stock Settings", self.settings_name)
		group = frappe.db.get_value(
			"Account", {"company": self.company, "is_group": 1}, "name", order_by="lft asc"
		)
		doc.consignment_temporary_clearing_account = group
		with self.assertRaises(frappe.ValidationError):
			doc.validate()
		doc.reload()
		doc.consignment_temporary_clearing_account = accounts["temporary"]
		doc.save(ignore_permissions=True)

	def test_default_warehouse_must_belong_to_company(self):
		doc = frappe.get_doc("Consignment Stock Settings", self.settings_name)
		other = frappe.db.get_value(
			"Warehouse", {"company": ("!=", self.company), "is_group": 0}, "name"
		)
		if not other:
			self.skipTest("No warehouse from another company available")
		original = doc.default_consignment_warehouse
		doc.default_consignment_warehouse = other
		with self.assertRaises(frappe.ValidationError):
			doc.validate()
		doc.reload()
		doc.default_consignment_warehouse = original
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
