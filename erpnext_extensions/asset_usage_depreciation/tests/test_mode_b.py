# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

import unittest

from erpnext_extensions.asset_usage_depreciation.services.accounting_amounts import to_depr_amount
from erpnext_extensions.asset_usage_depreciation.services.mode_b import redistribute_unposted_amounts


class TestModeB(unittest.TestCase):
	def test_redistribute_by_weights_whole_numbers(self):
		rows = [
			{"journal_entry": "JE-1", "depreciation_amount": 10, "usage_factor": 1.0, "schedule_date": "2026-01-31"},
			{"journal_entry": None, "depreciation_amount": 0, "usage_factor": 0.3, "schedule_date": "2026-02-28"},
			{"journal_entry": None, "depreciation_amount": 0, "usage_factor": 1.0, "schedule_date": "2026-03-31"},
			{"journal_entry": None, "depreciation_amount": 0, "usage_factor": 1.0, "schedule_date": "2026-04-30"},
		]
		# remaining 30 across weights 0.3+1+1=2.3
		redistribute_unposted_amounts(rows, 30)
		amounts = [r["depreciation_amount"] for r in rows if not r["journal_entry"]]
		self.assertEqual(sum(amounts), 30)
		self.assertEqual(amounts[0], to_depr_amount(30 * 0.3 / 2.3))
		self.assertGreater(amounts[1], amounts[0])
		self.assertEqual(rows[0]["depreciation_amount"], 10)
		for amount in amounts:
			self.assertEqual(amount, int(amount))

	def test_all_zero_weights_error(self):
		rows = [
			{"journal_entry": None, "depreciation_amount": 0, "usage_factor": 0.0, "schedule_date": "2026-02-28"},
			{"journal_entry": None, "depreciation_amount": 0, "usage_factor": 0.0, "schedule_date": "2026-03-31"},
		]
		with self.assertRaises(Exception):
			redistribute_unposted_amounts(rows, 20)

	def test_residue_on_last_row(self):
		rows = [
			{"journal_entry": None, "usage_factor": 1.0, "depreciation_amount": 0, "schedule_date": "2026-01-31"},
			{"journal_entry": None, "usage_factor": 1.0, "depreciation_amount": 0, "schedule_date": "2026-02-28"},
			{"journal_entry": None, "usage_factor": 1.0, "depreciation_amount": 0, "schedule_date": "2026-03-31"},
		]
		redistribute_unposted_amounts(rows, 100)
		amounts = [r["depreciation_amount"] for r in rows]
		self.assertEqual(amounts, [33, 33, 34])
		self.assertEqual(sum(amounts), 100)
