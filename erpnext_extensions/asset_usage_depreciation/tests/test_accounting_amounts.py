# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

"""Iran Accounting whole-number depreciation amount helpers."""

from __future__ import annotations

import unittest

from erpnext_extensions.asset_usage_depreciation.services.accounting_amounts import (
	sum_unposted_amounts,
	to_depr_amount,
)
from erpnext_extensions.asset_usage_depreciation.services.mode_b import apply_fixed_end_usage_adjustment
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

	def test_mode_b_balancing_preserves_whole_total(self):
		rows = [
			{"journal_entry": None, "depreciation_amount": 10, "_standard_amount": 10},
			{"journal_entry": None, "depreciation_amount": 10, "_standard_amount": 10},
			{"journal_entry": None, "depreciation_amount": 10, "_standard_amount": 10},
		]

		def resolve(idx, row):
			return 10, 0.3 if idx < 2 else 1.0

		apply_fixed_end_usage_adjustment(rows, 100, resolve_amount_and_factor=resolve)
		amounts = [r["depreciation_amount"] for r in rows]
		self.assertEqual(sum(amounts), 100)
		for amount in amounts:
			self.assertEqual(amount, int(amount))
			self.assertIsInstance(amount, int)
		self.assertEqual(amounts[0], 3)
		self.assertEqual(amounts[1], 3)
		self.assertEqual(amounts[2], 94)  # balancing

	def test_mode_b_large_remaining_whole_numbers(self):
		rows = [
			{"journal_entry": None, "depreciation_amount": 250_000, "_standard_amount": 250_000}
			for _ in range(4)
		]

		def resolve(idx, row):
			return 250_000, 0.3 if idx < 3 else 1.0

		apply_fixed_end_usage_adjustment(rows, 1_000_001, resolve_amount_and_factor=resolve)
		amounts = [r["depreciation_amount"] for r in rows]
		self.assertEqual(sum(amounts), 1_000_001)
		for amount in amounts:
			self.assertEqual(amount, int(amount))
		self.assertEqual(amounts[0], to_depr_amount(250_000 * 0.3))

	def test_sum_unposted_skips_posted(self):
		rows = [
			{"journal_entry": "JE-1", "depreciation_amount": 50},
			{"journal_entry": None, "depreciation_amount": 10.4},
			{"journal_entry": None, "depreciation_amount": 20.6},
		]
		self.assertEqual(sum_unposted_amounts(rows), 31)
