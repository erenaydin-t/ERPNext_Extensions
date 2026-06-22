# Copyright (c) 2026, ERPNext Extensions contributors

from __future__ import annotations

import unittest

import frappe
from frappe.tests.utils import FrappeTestCase

from erpnext_extensions.iran_accounting.diagnostics import (
	check_company_fractional_irr,
	check_purchase_invoice,
	check_stock_entry,
	check_voucher,
)


class TestDiagnostics(FrappeTestCase):
	def test_check_stock_entry_missing(self):
		with self.assertRaises(Exception):
			check_stock_entry("STE-DOES-NOT-EXIST-99999")

	def test_check_irr_fractional_rows_runs(self):
		out = check_company_fractional_irr(limit=5)
		self.assertIn("fractional_gl", out)
		self.assertIn("status", out)

	def test_check_voucher_stock_entry_live(self):
		if not frappe.db.exists("Stock Entry", "MAT-STE-2026-00005"):
			self.skipTest("MAT-STE-2026-00005 not on site")
		out = check_voucher("Stock Entry", "MAT-STE-2026-00005")
		self.assertEqual(out["status"], "PASS", msg=out)

	def test_check_purchase_invoice_runs_if_exists(self):
		name = frappe.db.get_value("Purchase Invoice", {"docstatus": 1}, "name")
		if not name:
			self.skipTest("No submitted PI")
		out = check_purchase_invoice(name)
		self.assertIn("status", out)


if __name__ == "__main__":
	unittest.main()
