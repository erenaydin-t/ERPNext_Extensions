# Copyright (c) 2026, ERPNext Extensions contributors

from __future__ import annotations

import unittest

import frappe

from erpnext_extensions.iran_accounting.e2e_bootstrap import (
	ensure_test_item,
	get_irr_company,
	get_warehouse,
	submit_opening_stock_reconciliation,
)
from erpnext_extensions.iran_accounting.stock_ledger_report import _align_stock_reconciliation_report_row
from erpnext_extensions.iran_accounting.stock_reconciliation_debug import _report_row_for_voucher


class TestStockLedgerReportOpeningSR(unittest.TestCase):
	def setUp(self):
		import erpnext_extensions.iran_accounting  # noqa: F401

		frappe.set_user("Administrator")
		self.company = get_irr_company(None)
		self.warehouse = get_warehouse(self.company)

	def test_align_does_not_copy_valuation_to_outgoing_rate(self):
		row = {
			"voucher_type": "Stock Reconciliation",
			"in_qty": 0,
			"out_qty": 0,
			"qty_after_transaction": 6,
			"stock_value_difference": 18000,
			"valuation_rate": 3000,
			"incoming_rate": 0,
			"in_out_rate": 0,
		}
		_align_stock_reconciliation_report_row(row)
		self.assertEqual(row["in_qty"], 6)
		self.assertEqual(row["outgoing_rate"] if "outgoing_rate" in row else row["in_out_rate"], 0)
		self.assertEqual(row["in_out_rate"], 0)
		self.assertEqual(row["incoming_rate"], 3000)

	def test_align_clears_valuation_copied_to_outgoing_rate(self):
		row = {
			"voucher_type": "Stock Reconciliation",
			"in_qty": 100,
			"out_qty": 0,
			"qty_after_transaction": 100,
			"stock_value_difference": 300000,
			"valuation_rate": 3000,
			"incoming_rate": 3000,
			"in_out_rate": 3000,
		}
		_align_stock_reconciliation_report_row(row)
		self.assertEqual(row["in_out_rate"], 0)

	def test_opening_non_batch_report_outgoing_rate_zero(self):
		item = ensure_test_item(self.company, prefix="IA-TEST-SR-OUTR")
		sr = submit_opening_stock_reconciliation(self.company, item, 6, 3000, self.warehouse)
		frappe.db.commit()
		sle = frappe.db.get_value(
			"Stock Ledger Entry",
			{"voucher_type": "Stock Reconciliation", "voucher_no": sr.name, "item_code": item},
			["outgoing_rate", "incoming_rate", "valuation_rate", "actual_qty"],
			as_dict=True,
		)
		self.assertEqual(sle.outgoing_rate, 0)
		posting = frappe.db.get_value("Stock Reconciliation", sr.name, "posting_date")
		rpt = _report_row_for_voucher(self.company, sr.name, str(posting))
		self.assertGreater(rpt.get("in_qty"), 0)
		self.assertEqual(rpt.get("out_qty"), 0)
		self.assertGreater(rpt.get("incoming_rate"), 0)
		self.assertEqual(rpt.get("in_out_rate"), 0)

	def test_align_negative_value_change_sets_outgoing_rate(self):
		row = {
			"voucher_type": "Stock Reconciliation",
			"in_qty": 0,
			"out_qty": 0,
			"qty_after_transaction": 4,
			"stock_value_difference": -600,
			"valuation_rate": 100,
			"incoming_rate": 100,
			"in_out_rate": 0,
		}
		_align_stock_reconciliation_report_row(row)
		self.assertEqual(row["out_qty"], -6)
		self.assertEqual(row["in_qty"], 0)
		self.assertEqual(row["incoming_rate"], 0)
		self.assertEqual(row["in_out_rate"], 100)
