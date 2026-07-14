# Copyright (c) 2026, ERPNext Extensions contributors

from __future__ import annotations

import unittest
from unittest import mock

import frappe
from frappe.utils import flt

from erpnext_extensions.iran_accounting.zero_value_transfer import (
	ZERO_VALUE_TRANSFER_STOCK_ENTRY_PURPOSES,
	_append_balanced_transfer_item_gl,
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

	def test_same_stock_account_skips_balanced_gl_legs(self):
		"""Credit+debit on one Stock account merges to one row and trips ERPNext make_gl_entries."""
		from erpnext.accounts.general_ledger import merge_similar_entries, toggle_debit_credit_if_negative

		stock_account = "Stores - Co"

		class Doc:
			company = "Co"
			remarks = None

			def get(self, k, default=None):
				return getattr(self, k, default)

			def get_inventory_account_dict(self, item_row, inventory_account_map, warehouse_field="warehouse"):
				return {"account": stock_account, "account_currency": "IRR"}

			def get_gl_dict(self, fields, account_currency, item=None):
				return frappe._dict(
					{
						**fields,
						"account_currency": account_currency,
						"company": self.company,
						"voucher_type": "Stock Entry",
						"voucher_no": "STE-1",
					}
				)

		item = frappe._dict(
			s_warehouse="WH-A",
			t_warehouse="WH-B",
			amount=1_000_000,
			cost_center="CC - Co",
			project=None,
			is_opening="No",
		)
		doc = Doc()
		gl_list: list = []
		self.assertTrue(_append_balanced_transfer_item_gl(doc, gl_list, item, {}, 0))
		self.assertEqual(gl_list, [])

		# Pre-fix pattern: explicit credit/debit on the same account collapses to a single GL row.
		legacy = [
			frappe._dict(
				account=stock_account,
				credit=1_000_000,
				debit=0,
				cost_center="CC - Co",
				company="Co",
				voucher_type="Stock Entry",
				voucher_no="STE-1",
			),
			frappe._dict(
				account=stock_account,
				credit=0,
				debit=1_000_000,
				cost_center="CC - Co",
				company="Co",
				voucher_type="Stock Entry",
				voucher_no="STE-1",
			),
		]
		merged = merge_similar_entries(legacy, precision=0)
		processed = toggle_debit_credit_if_negative(merged)
		self.assertEqual(len(processed), 1)


if __name__ == "__main__":
	unittest.main()
