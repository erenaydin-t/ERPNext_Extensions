# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

"""Iran Accounting whole-number depreciation amount helpers."""

from __future__ import annotations

import unittest

from erpnext_extensions.asset_usage_depreciation.services.accounting_amounts import (
	sum_unposted_amounts,
	to_depr_amount,
)
from erpnext_extensions.asset_usage_depreciation.services.mode_b import redistribute_unposted_amounts
from erpnext_extensions.iran_accounting.core.rounding import round_currency


class TestAccountingAmounts(unittest.TestCase):
	def test_to_depr_amount_uses_iran_half_up(self):
		self.assertEqual(to_depr_amount(1.5), 2)
		self.assertEqual(to_depr_amount(1.4), 1)
		self.assertEqual(to_depr_amount(10.25), 10)
		self.assertEqual(to_depr_amount(10.5), 11)
		self.assertEqual(to_depr_amount(None), 0)
		self.assertEqual(to_depr_amount(3_000_000.25), 3_000_000)

	def test_delegates_to_round_currency_precision_0(self):
		for value in (0.5, 1.5, 2.5, 100.49, 100.5, 5333.333333):
			self.assertEqual(to_depr_amount(value), round_currency(value, 0))
			self.assertIsInstance(to_depr_amount(value), int)

	def test_mode_b_awkward_100_with_0_3_0_3_1_0(self):
		rows = [
			{"journal_entry": None, "usage_factor": 0.3, "depreciation_amount": 0, "schedule_date": "2026-01-31"},
			{"journal_entry": None, "usage_factor": 0.3, "depreciation_amount": 0, "schedule_date": "2026-02-28"},
			{"journal_entry": None, "usage_factor": 1.0, "depreciation_amount": 0, "schedule_date": "2026-03-31"},
		]
		redistribute_unposted_amounts(rows, 100)
		amounts = [r["depreciation_amount"] for r in rows]
		self.assertEqual(sum(amounts), 100)
		for amount in amounts:
			self.assertEqual(amount, int(amount))
			self.assertIsInstance(amount, int)
		# Proportional: reduced rows lower than full-weight row
		self.assertLess(amounts[0], amounts[2])
		self.assertLess(amounts[1], amounts[2])

	def test_mode_b_awkward_1000001(self):
		weights = [0.3, 1.0, 0.3, 1.0]
		rows = [
			{
				"journal_entry": None,
				"usage_factor": w,
				"depreciation_amount": 0,
				"schedule_date": f"2026-0{i+1}-28",
			}
			for i, w in enumerate(weights)
		]
		redistribute_unposted_amounts(rows, 1_000_001)
		amounts = [r["depreciation_amount"] for r in rows]
		self.assertEqual(sum(amounts), 1_000_001)
		for amount in amounts:
			self.assertEqual(amount, int(amount))

	def test_sum_unposted_skips_posted(self):
		rows = [
			{"journal_entry": "JE-1", "depreciation_amount": 50},
			{"journal_entry": None, "depreciation_amount": 10.4},
			{"journal_entry": None, "depreciation_amount": 20.6},
		]
		self.assertEqual(sum_unposted_amounts(rows), 31)
