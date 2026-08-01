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
	resolve_warehouse_inventory_account,
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
		cls.inv = resolve_warehouse_inventory_account(cls.wh, cls.company)
		cls.temp = cls.settings.consignment_temporary_clearing_account

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
		self.assertEqual(se.items[0].expense_account, self.temp)

		gl = gl_rows_for("Stock Entry", se.name)
		debit_inv = sum(flt(r.debit) for r in gl if r.account == self.inv)
		credit_temp = sum(flt(r.credit) for r in gl if r.account == self.temp)
		self.assertEqual(debit_inv, 10000)
		self.assertEqual(credit_temp, 10000)

	def test_receipt_uses_warehouse_account_not_settings(self):
		"""Inventory leg must come from warehouse resolution; settings has no inventory field."""
		meta = frappe.get_meta("Consignment Stock Settings")
		self.assertFalse(meta.has_field("consignment_inventory_account"))
		self.assertTrue(self.inv)
		se = make_consignment_receipt(
			company=self.company,
			warehouse=self.wh,
			item_code=ensure_test_item(self.company, "CS-RCV-WH"),
			qty=2,
			rate=500,
			party_type="Supplier",
			party=self.supplier,
			stock_entry_type=self.types["receipt"],
		)
		gl_accounts = {r.account for r in gl_rows_for("Stock Entry", se.name)}
		self.assertIn(self.inv, gl_accounts)

	def test_missing_warehouse_account_fails(self):
		from unittest.mock import patch

		from erpnext_extensions.consignment_stock.accounting import resolve_warehouse_account

		# Standard ERPNext may fall back to any Stock account; force unresolved map entry
		with patch(
			"erpnext.stock.get_warehouse_account_map",
			return_value={self.wh: frappe._dict()},
		):
			with self.assertRaises(frappe.ValidationError) as ctx:
				resolve_warehouse_account(self.wh, self.company)
			self.assertIn("No stock account could be resolved", str(ctx.exception))

	def test_non_stock_resolved_account_fails(self):
		from erpnext_extensions.consignment_stock.accounting import resolve_warehouse_account

		expense = frappe.db.get_value(
			"Account",
			{"company": self.company, "root_type": "Expense", "is_group": 0, "account_type": ("!=", "Stock")},
			"name",
		)
		if not expense:
			self.skipTest("No non-stock expense account")
		parent = frappe.db.get_value(
			"Warehouse", {"company": self.company, "is_group": 1}, "name"
		)
		wh = frappe.get_doc(
			{
				"doctype": "Warehouse",
				"warehouse_name": f"CS Bad Acc {frappe.generate_hash(length=5)}",
				"company": self.company,
				"parent_warehouse": parent,
				"account": expense,
				"is_group": 0,
			}
		)
		wh.insert(ignore_permissions=True)
		frappe.flags.setdefault("warehouse_account_map", {}).pop(self.company, None)
		with self.assertRaises(frappe.ValidationError) as ctx:
			resolve_warehouse_account(wh.name, self.company)
		self.assertIn("must be a Stock account", str(ctx.exception))

	def test_disabled_warehouse_fails(self):
		from erpnext_extensions.consignment_stock.accounting import resolve_warehouse_account

		parent = frappe.db.get_value(
			"Warehouse", {"company": self.company, "is_group": 1}, "name"
		)
		wh = frappe.get_doc(
			{
				"doctype": "Warehouse",
				"warehouse_name": f"CS Disabled {frappe.generate_hash(length=5)}",
				"company": self.company,
				"parent_warehouse": parent,
				"account": self.inv,
				"is_group": 0,
				"disabled": 1,
			}
		)
		wh.insert(ignore_permissions=True)
		with self.assertRaises(frappe.ValidationError) as ctx:
			resolve_warehouse_account(wh.name, self.company)
		self.assertIn("disabled", str(ctx.exception).lower())
	def test_group_warehouse_fails(self):
		from erpnext_extensions.consignment_stock.accounting import resolve_warehouse_account

		group = frappe.db.get_value(
			"Warehouse", {"company": self.company, "is_group": 1}, "name"
		)
		if not group:
			self.skipTest("No group warehouse")
		with self.assertRaises(frappe.ValidationError):
			resolve_warehouse_account(group, self.company)

	def test_warehouse_other_company_fails(self):
		from erpnext_extensions.consignment_stock.accounting import resolve_warehouse_account

		other = frappe.db.get_value(
			"Warehouse", {"company": ("!=", self.company), "is_group": 0}, "name"
		)
		if not other:
			self.skipTest("No warehouse from another company")
		with self.assertRaises(frappe.ValidationError):
			resolve_warehouse_account(other, self.company)

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
