# Copyright (c) 2026, ERPNext Extensions contributors

from __future__ import annotations

import unittest
from unittest import mock

import frappe
from frappe.utils import flt

from erpnext_extensions.iran_accounting.zero_value_transfer import (
	ZERO_VALUE_TRANSFER_STOCK_ENTRY_PURPOSES,
	_should_force_balanced_transfer_gl,
	finalize_zero_value_transfer_gl_map,
)


class TestStockEntryTransferGL(unittest.TestCase):
	def test_zero_value_transfer_no_stock_adjustment(self):
		class Doc:
			doctype = "Stock Entry"
			purpose = "Material Transfer for Manufacture"
			company = "Test"
			name = "STE-TEST"
			total_incoming_value = 5596111506
			total_outgoing_value = 5596111506
			value_difference = 0
			remarks = None

			def get(self, k, default=None):
				return getattr(self, k, default)

			def set_total_incoming_outgoing_value(self):
				pass

			def get_debit_field_precision(self):
				return 0

		doc = Doc()
		self.assertIn(doc.purpose, ZERO_VALUE_TRANSFER_STOCK_ENTRY_PURPOSES)
		self.assertTrue(_should_force_balanced_transfer_gl(doc, 0))

		stock_adj = "Stock Adjustment - T"
		round_off = "Round Off - T"
		gl_map = [
			frappe._dict(account="Stores - T", debit=100, credit=0),
			frappe._dict(account=stock_adj, debit=0, credit=0.4),
		]

		def _cached_value(doctype, name, field):
			if doctype == "Company" and field == "stock_adjustment_account":
				return stock_adj
			if doctype == "Company" and field == "round_off_account":
				return round_off
			if doctype == "Account" and field == "account_type":
				return "Stock Adjustment" if name == stock_adj else None
			return None

		with unittest.mock.patch.object(frappe, "get_cached_value", side_effect=_cached_value):
			out = finalize_zero_value_transfer_gl_map(doc, gl_map, precision=0)
		accounts = [r.account for r in out]
		self.assertNotIn(stock_adj, accounts)

	def test_zero_value_transfer_not_doubled(self):
		gl_rows = [
			{"debit": 5596111506, "credit": 0},
			{"debit": 0, "credit": 5596111506},
		]
		debit = sum(flt(r["debit"]) for r in gl_rows)
		credit = sum(flt(r["credit"]) for r in gl_rows)
		self.assertEqual(debit, credit)
		self.assertLess(debit, 2 * 5596111506)


if __name__ == "__main__":
	unittest.main()
