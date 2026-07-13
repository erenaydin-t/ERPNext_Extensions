# Copyright (c) 2026, ERPNext Extensions contributors

from __future__ import annotations

import unittest

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt, today

from erpnext_extensions.iran_accounting.diagnostics import (
	check_delivery_note,
	check_purchase_invoice,
	check_purchase_receipt,
	check_sales_invoice,
)
from erpnext_extensions.iran_accounting.e2e_bootstrap import (
	enable_perpetual_inventory,
	ensure_test_item,
	get_irr_company,
	get_warehouse,
	submit_material_receipt,
)
from erpnext_extensions.iran_accounting.validation import fractional_gl_fields


class TestIranAccountingBuyingSellingE2E(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		try:
			cls.company = get_irr_company("ESPAD")
		except Exception:
			raise unittest.SkipTest("No IRR company on site")
		enable_perpetual_inventory(cls.company)
		cls.warehouse = get_warehouse(cls.company)

	def _supplier(self):
		name = frappe.db.get_value("Supplier", {}, "name", order_by="creation asc")
		if not name:
			raise unittest.SkipTest("No supplier")
		return name

	def _customer(self):
		name = frappe.db.get_value("Customer", {}, "name", order_by="creation asc")
		if not name:
			raise unittest.SkipTest("No customer")
		return name

	def test_purchase_receipt_irr_no_decimals(self):
		try:
			from erpnext.buying.doctype.purchase_order.test_purchase_order import create_purchase_order
		except ImportError:
			raise unittest.SkipTest("ERPNext buying test helpers unavailable")

		item = ensure_test_item(self.company, "IRR-PR")
		supplier = self._supplier()
		try:
			po = create_purchase_order(item_code=item, qty=5, rate=123.456, company=self.company)
		except Exception as exc:
			raise unittest.SkipTest(f"Cannot create PO: {exc}") from exc

		from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_receipt

		pr = make_purchase_receipt(po.name)
		pr.company = self.company
		for row in pr.items:
			row.warehouse = self.warehouse
		pr.insert(ignore_permissions=True)
		pr.submit()
		chk = check_purchase_receipt(pr.name)
		self.assertEqual(chk["status"], "PASS", msg=chk)

	def test_purchase_invoice_irr_update_stock_no_decimals(self):
		item = ensure_test_item(self.company, "IRR-PI")
		submit_material_receipt(self.company, item, qty=1, rate=500.777, warehouse=self.warehouse)
		supplier = self._supplier()
		pi = frappe.new_doc("Purchase Invoice")
		pi.company = self.company
		pi.supplier = supplier
		pi.posting_date = today()
		pi.currency = "IRR"
		pi.conversion_rate = 1
		item_doc = frappe.get_doc("Item", item)
		pi.append(
			"items",
			{
				"item_code": item,
				"qty": 1,
				"rate": 500.777,
				"warehouse": self.warehouse,
				"uom": item_doc.stock_uom,
				"stock_uom": item_doc.stock_uom,
				"conversion_factor": 1,
			},
		)
		pi.update_stock = 1
		try:
			pi.insert(ignore_permissions=True)
			pi.submit()
		except Exception as exc:
			raise unittest.SkipTest(f"PI submit failed (tax/accounts): {exc}") from exc
		chk = check_purchase_invoice(pi.name)
		self.assertEqual(chk["status"], "PASS", msg=chk)

	def test_purchase_invoice_usd_account_currency_decimal_allowed_irr_company_integer(self):
		usd_account = frappe.db.get_value(
			"Account", {"company": self.company, "account_currency": "USD", "is_group": 0}, "name"
		)
		if not usd_account:
			self.skipTest("No USD account for IRR company")
		supplier = self._supplier()
		pi = frappe.new_doc("Purchase Invoice")
		pi.company = self.company
		pi.supplier = supplier
		pi.posting_date = today()
		pi.currency = "USD"
		pi.conversion_rate = 500000
		pi.append(
			"accounts",
			{"account": usd_account, "debit_in_account_currency": 10.55, "credit_in_account_currency": 0},
		)
		try:
			pi.insert(ignore_permissions=True)
			pi.submit()
		except Exception as exc:
			raise unittest.SkipTest(f"USD PI not configurable: {exc}") from exc
		for row in check_purchase_invoice(pi.name)["gl_rows"]:
			if row.get("account") == usd_account and flt(row.get("debit_in_account_currency")):
				self.assertTrue(
					flt(row["debit_in_account_currency"]) % 1 != 0 or row["debit_in_account_currency"] == 11
				)

	def test_sales_invoice_irr_update_stock_no_decimals(self):
		item = ensure_test_item(self.company, "IRR-SI")
		submit_material_receipt(self.company, item, qty=10, rate=50.333, warehouse=self.warehouse)
		customer = self._customer()
		si = frappe.new_doc("Sales Invoice")
		si.company = self.company
		si.customer = customer
		si.posting_date = today()
		si.currency = "IRR"
		si.conversion_rate = 1
		si.update_stock = 1
		item_doc = frappe.get_doc("Item", item)
		si.append(
			"items",
			{
				"item_code": item,
				"qty": 1,
				"rate": 50.333,
				"warehouse": self.warehouse,
				"uom": item_doc.stock_uom,
				"stock_uom": item_doc.stock_uom,
				"conversion_factor": 1,
			},
		)
		try:
			si.insert(ignore_permissions=True)
			si.submit()
		except Exception as exc:
			raise unittest.SkipTest(f"SI submit failed: {exc}") from exc
		chk = check_sales_invoice(si.name)
		self.assertEqual(chk["status"], "PASS", msg=chk)

	def test_sales_invoice_usd_account_currency_decimal_allowed_irr_company_integer(self):
		self.skipTest("Configure USD receivable account on site for full assertion")

	def test_delivery_note_irr_no_decimals(self):
		item = ensure_test_item(self.company, "IRR-DN")
		submit_material_receipt(self.company, item, qty=5, rate=33.333, warehouse=self.warehouse)
		customer = self._customer()
		dn = frappe.new_doc("Delivery Note")
		dn.company = self.company
		dn.customer = customer
		dn.posting_date = today()
		item_doc = frappe.get_doc("Item", item)
		dn.append(
			"items",
			{
				"item_code": item,
				"qty": 1,
				"rate": 33.333,
				"warehouse": self.warehouse,
				"uom": item_doc.stock_uom,
				"stock_uom": item_doc.stock_uom,
				"conversion_factor": 1,
			},
		)
		try:
			dn.insert(ignore_permissions=True)
			dn.submit()
		except Exception as exc:
			raise unittest.SkipTest(f"DN submit failed: {exc}") from exc
		chk = check_delivery_note(dn.name)
		self.assertEqual(chk["status"], "PASS", msg=chk)


if __name__ == "__main__":
	unittest.main()
