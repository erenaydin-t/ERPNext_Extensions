# Copyright (c) 2026, ERPNext Extensions contributors

from __future__ import annotations

import unittest

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from erpnext_extensions.iran_accounting.diagnostics import (
	check_stock_entry,
	repost_and_check_stock_entry,
)
from erpnext_extensions.iran_accounting.e2e_bootstrap import (
	enable_perpetual_inventory,
	ensure_test_item,
	get_irr_company,
	get_second_warehouse,
	get_warehouse,
	submit_material_receipt,
	submit_material_transfer,
	submit_opening_stock_reconciliation,
)
from erpnext_extensions.iran_accounting.validation import (
	fractional_gl_fields,
	fractional_sle_fields,
	stock_adj_round_off_rows,
)


class TestIranAccountingStockE2E(FrappeTestCase):
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

	def test_opening_stock_or_stock_reconciliation_irr_no_decimals(self):
		item = ensure_test_item(self.company, "IRR-OPEN")
		sr = submit_opening_stock_reconciliation(
			self.company, item, qty=7, rate=1234.567, warehouse=self.warehouse
		)
		gl, sle = self._snapshot("Stock Reconciliation", sr.name)
		self.assertFalse(fractional_sle_fields(sle[0], self.company) if sle else False)
		for row in sle:
			self.assertFalse(fractional_sle_fields(row, self.company))
		for row in gl:
			self.assertFalse(fractional_gl_fields(row, self.company))

	def test_material_receipt_irr_no_decimals(self):
		item = ensure_test_item(self.company, "IRR-MR")
		se = submit_material_receipt(self.company, item, qty=3, rate=10.333, warehouse=self.warehouse)
		chk = check_stock_entry(se.name)
		self.assertEqual(chk["status"], "PASS", msg=chk)

	def test_material_transfer_irr_no_adjustment_no_double_no_decimals(self):
		item = ensure_test_item(self.company, "IRR-MT")
		submit_material_receipt(self.company, item, qty=5, rate=99.99, warehouse=self.warehouse)
		to_wh = get_second_warehouse(self.company, self.warehouse)
		se = submit_material_transfer(self.company, item, qty=2, from_wh=self.warehouse, to_wh=to_wh)
		chk = check_stock_entry(se.name)
		self.assertEqual(chk["status"], "PASS", msg=chk)
		self.assertFalse(chk["checks"].get("no_stock_adjustment_or_round_off", False), msg=chk)

	def test_mtfm_preview_submit_repost_no_adjustment_no_double_no_decimals(self):
		if frappe.db.exists("Stock Entry", "PO-JOB00049-1"):
			from erpnext_extensions.iran_accounting.e2e_bootstrap import preview_gl_totals, preview_stock_entry_gl

			se = frappe.get_doc("Stock Entry", "PO-JOB00049-1")
			preview = preview_stock_entry_gl(se.company, se.name)
			debit, credit = preview_gl_totals(preview)
			self.assertEqual(flt(debit), flt(se.total_incoming_value))
			self.assertEqual(flt(credit), flt(se.total_outgoing_value))
			chk = repost_and_check_stock_entry("PO-JOB00049-1")
			self.assertEqual(chk["status"], "PASS", msg=chk)
			return
		self.skipTest("PO-JOB00049-1 not on site; manual MTfM E2E required")

	def test_manufacture_irr_no_db_or_print_decimals(self):
		if frappe.db.exists("Stock Entry", "MAT-STE-2026-00005"):
			chk = check_stock_entry("MAT-STE-2026-00005")
			self.assertEqual(chk["status"], "PASS", msg=chk)
			return
		self.skipTest("MAT-STE-2026-00005 not on site; manual manufacture E2E required")

	def _snapshot(self, doctype, name):
		from erpnext_extensions.iran_accounting.validation import fetch_gl_rows, fetch_sle_rows

		return fetch_gl_rows(doctype, name), fetch_sle_rows(doctype, name)



if __name__ == "__main__":
	unittest.main()
