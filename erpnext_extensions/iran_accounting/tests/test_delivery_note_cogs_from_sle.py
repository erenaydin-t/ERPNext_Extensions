# Copyright (c) 2026, ERPNext Extensions contributors
"""COGS on selling vouchers must follow SLE stock_value_difference, not selling amount."""

from __future__ import annotations

import unittest

import frappe
from frappe.utils import flt, today

from erpnext_extensions.iran_accounting.diagnostics import check_delivery_note
from erpnext_extensions.iran_accounting.domain.stock_entry_ledger_contract import (
	enforce_stock_entry_ledger_contract,
)
from erpnext_extensions.iran_accounting.e2e_bootstrap import (
	enable_perpetual_inventory,
	ensure_test_item,
	get_irr_company,
	get_second_warehouse,
	get_warehouse,
	submit_material_receipt,
	submit_material_transfer,
)
from erpnext_extensions.iran_accounting.integration.bootstrap import apply
from erpnext_extensions.iran_accounting.validation import fetch_gl_rows, gl_debit_credit_totals


def _sle_abs_sum(voucher_type: str, voucher_no: str) -> float:
	return abs(
		flt(
			frappe.db.sql(
				"""
				select coalesce(sum(stock_value_difference), 0)
				from `tabStock Ledger Entry`
				where voucher_type=%s and voucher_no=%s and is_cancelled=0
				""",
				(voucher_type, voucher_no),
			)[0][0]
		)
	)


def _gl_stock_magnitude(voucher_type: str, voucher_no: str, company: str) -> float:
	"""Stock-account movement magnitude, excluding revenue/receivable etc."""
	rows = fetch_gl_rows(voucher_type, voucher_no)
	stock_accounts = set(
		frappe.db.sql_list(
			"""
			select name from `tabAccount`
			where company=%s and account_type='Stock' and is_group=0
			""",
			company,
		)
	)
	stock_net = 0.0
	for r in rows:
		if r.get("account") in stock_accounts:
			stock_net += flt(r.get("debit")) - flt(r.get("credit"))
	return abs(stock_net)


class TestDeliveryNoteCogsFromSle(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		apply()
		frappe.set_user("Administrator")
		cls.company = get_irr_company("ESPAD")
		enable_perpetual_inventory(cls.company)
		cls.wh = get_warehouse(cls.company)
		cls.wh2 = get_second_warehouse(cls.company, cls.wh)

	def _customer(self, prefix: str = "IA-DN-COGS"):
		name = frappe.db.get_value("Customer", {"customer_name": ("like", f"{prefix}-%")}, "name")
		if name:
			return name
		c = frappe.new_doc("Customer")
		c.customer_name = f"{prefix}-{frappe.generate_hash(length=6)}"
		c.customer_type = "Company"
		c.insert(ignore_permissions=True)
		return c.name

	def test_delivery_note_cogs_uses_stock_valuation_not_selling(self):
		"""Test 1: cost 100k, sell 175k, qty 10 → COGS 1M not 1.75M."""
		item = ensure_test_item(self.company, "IA-DN-COGS-ITEM")
		cost_rate = 100_000
		sell_rate = 175_000
		qty = 10
		submit_material_receipt(self.company, item, qty=qty, rate=cost_rate, warehouse=self.wh)

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
				"qty": qty,
				"rate": sell_rate,
				"warehouse": self.wh,
				"uom": item_doc.stock_uom,
				"stock_uom": item_doc.stock_uom,
				"conversion_factor": 1,
			},
		)
		dn.insert(ignore_permissions=True)
		dn.submit()
		frappe.db.commit()

		expected_revenue = qty * sell_rate
		expected_cogs = qty * cost_rate
		sle_cogs = _sle_abs_sum("Delivery Note", dn.name)
		gl_mag = _gl_stock_magnitude("Delivery Note", dn.name, self.company)

		self.assertEqual(sle_cogs, expected_cogs)
		self.assertEqual(gl_mag, expected_cogs)
		self.assertNotEqual(gl_mag, expected_revenue)
		self.assertEqual(expected_revenue, 1_750_000)
		self.assertEqual(expected_cogs, 1_000_000)

		chk = check_delivery_note(dn.name)
		self.assertEqual(chk["status"], "PASS", chk)

	def test_sales_invoice_update_stock_cogs_from_sle(self):
		"""Test 2: SI with update_stock uses SLE, not selling rate."""
		item = ensure_test_item(self.company, "IA-SI-STK-COGS")
		cost_rate = 50_000
		sell_rate = 90_000
		qty = 4
		submit_material_receipt(self.company, item, qty=qty, rate=cost_rate, warehouse=self.wh)

		si = frappe.new_doc("Sales Invoice")
		si.company = self.company
		si.customer = self._customer("IA-SI-STK-COGS")
		si.posting_date = today()
		si.update_stock = 1
		item_doc = frappe.get_doc("Item", item)
		si.append(
			"items",
			{
				"item_code": item,
				"qty": qty,
				"rate": sell_rate,
				"warehouse": self.wh,
				"uom": item_doc.stock_uom,
				"stock_uom": item_doc.stock_uom,
				"conversion_factor": 1,
			},
		)
		si.insert(ignore_permissions=True)
		si.submit()
		frappe.db.commit()

		sle_cogs = _sle_abs_sum("Sales Invoice", si.name)
		gl_mag = _gl_stock_magnitude("Sales Invoice", si.name, self.company)
		self.assertEqual(sle_cogs, qty * cost_rate)
		self.assertEqual(gl_mag, sle_cogs)
		self.assertNotEqual(gl_mag, qty * sell_rate)

	def test_stock_entry_zero_value_transfer_still_passes_contract(self):
		"""Test 3: Stock Entry IRR / zero-value transfer path unchanged."""
		item = ensure_test_item(self.company, "IA-STE-ZVT-COGS")
		submit_material_receipt(self.company, item, qty=20, rate=3333, warehouse=self.wh)
		# Use integer qty for sites where stock UOM must be whole number.
		se = submit_material_transfer(self.company, item, 3, self.wh, self.wh2)
		se.submit()
		frappe.db.commit()
		out = enforce_stock_entry_ledger_contract(se.name, self.company, raise_on_fail=True)
		self.assertEqual(out["status"], "PASS", out)


if __name__ == "__main__":
	unittest.main()
