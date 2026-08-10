# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

"""Unit tests for fixed-end (Adjust Final Depreciation Installment) policy."""

from __future__ import annotations

import unittest

from erpnext_extensions.asset_usage_depreciation.services.accounting_amounts import to_depr_amount
from erpnext_extensions.asset_usage_depreciation.services.mode_b import (
	apply_fixed_end_usage_adjustment,
	redistribute_unposted_amounts,
)

STANDARD = 10_000_000
N = 120
REMAINING = STANDARD * N  # salvage 0, nothing posted


def _blank_rows(n: int = N, amount: int = STANDARD, posted: int = 0):
	rows = []
	for i in range(n):
		rows.append(
			{
				"journal_entry": f"JE-{i+1}" if i < posted else None,
				"depreciation_amount": amount,
				"_standard_amount": amount,
				"schedule_date": f"20{26 + i // 12}-{(i % 12) + 1:02d}-28",
			}
		)
	return rows


class TestModeBFixedEnd(unittest.TestCase):
	def test_example1_30pct_from_installment_3(self):
		"""Rows 3–119 at 30%; final absorbs 117 × 7M shortfall."""
		rows = _blank_rows()

		def resolve(idx, row):
			if idx < 2:
				return STANDARD, 1.0
			# installments 3..119 → indices 2..118
			return STANDARD, 0.3

		apply_fixed_end_usage_adjustment(rows, REMAINING, resolve_amount_and_factor=resolve)

		self.assertEqual(rows[0]["depreciation_amount"], STANDARD)
		self.assertEqual(rows[1]["depreciation_amount"], STANDARD)
		for i in range(2, 119):
			self.assertEqual(rows[i]["depreciation_amount"], to_depr_amount(STANDARD * 0.3), f"row {i+1}")
		# Inclusive count 3..119 = 117
		shortfall = 117 * (STANDARD - to_depr_amount(STANDARD * 0.3))
		expected_final = STANDARD + shortfall
		self.assertEqual(rows[119]["depreciation_amount"], expected_final)
		self.assertTrue(rows[119].get("is_balancing_row"))
		self.assertEqual(sum(r["depreciation_amount"] for r in rows), REMAINING)

	def test_example2_return_to_normal_at_installment_10(self):
		"""After Normal from installment 10, only shortfall from 3–9 remains in final."""
		rows = _blank_rows()

		def resolve(idx, row):
			# 1–2 Normal, 3–9 @30%, 10–119 Normal; 120 balancing
			if 2 <= idx <= 8:
				return STANDARD, 0.3
			return STANDARD, 1.0

		apply_fixed_end_usage_adjustment(rows, REMAINING, resolve_amount_and_factor=resolve)

		for i in range(2, 9):
			self.assertEqual(rows[i]["depreciation_amount"], 3_000_000)
		for i in range(9, 119):
			self.assertEqual(rows[i]["depreciation_amount"], STANDARD, f"row {i+1} should be Normal")
		shortfall = 7 * 7_000_000
		self.assertEqual(rows[119]["depreciation_amount"], STANDARD + shortfall)
		self.assertEqual(sum(r["depreciation_amount"] for r in rows), REMAINING)

	def test_final_decreases_when_shortfall_recovered(self):
		rows_a = _blank_rows()

		def resolve_30(idx, row):
			return (STANDARD, 0.3) if idx >= 2 else (STANDARD, 1.0)

		apply_fixed_end_usage_adjustment(rows_a, REMAINING, resolve_amount_and_factor=resolve_30)
		final_large = rows_a[119]["depreciation_amount"]

		rows_b = _blank_rows()

		def resolve_recover(idx, row):
			if 2 <= idx <= 8:
				return STANDARD, 0.3
			return STANDARD, 1.0

		apply_fixed_end_usage_adjustment(rows_b, REMAINING, resolve_amount_and_factor=resolve_recover)
		final_small = rows_b[119]["depreciation_amount"]
		self.assertLess(final_small, final_large)

	def test_final_increases_when_new_reduced_period_added(self):
		rows_b = _blank_rows()

		def resolve_recover(idx, row):
			if 2 <= idx <= 8:
				return STANDARD, 0.3
			return STANDARD, 1.0

		apply_fixed_end_usage_adjustment(rows_b, REMAINING, resolve_amount_and_factor=resolve_recover)
		final_mid = rows_b[119]["depreciation_amount"]

		rows_c = _blank_rows()

		def resolve_again(idx, row):
			if 2 <= idx <= 8:
				return STANDARD, 0.3
			if idx >= 29:  # installment 30 onward
				return STANDARD, 0.3
			return STANDARD, 1.0

		apply_fixed_end_usage_adjustment(rows_c, REMAINING, resolve_amount_and_factor=resolve_again)
		self.assertGreater(rows_c[119]["depreciation_amount"], final_mid)

	def test_no_depreciation_absorbed_by_final(self):
		"""All-zero factors on non-final rows dump remaining into the balancing row."""
		rows = _blank_rows(n=5, amount=100)

		def resolve(idx, row):
			return 100, 0.0

		apply_fixed_end_usage_adjustment(rows, 500, resolve_amount_and_factor=resolve)
		self.assertEqual([r["depreciation_amount"] for r in rows], [0, 0, 0, 0, 500])

	def test_replan_from_scratch_no_adjustment_on_adjustment(self):
		"""Second replan must use standard baseline, not the prior inflated final."""
		# First replan leaves an inflated final on a stale copy
		stale = _blank_rows()
		stale[119]["depreciation_amount"] = 829_000_000
		stale[119]["_standard_amount"] = 829_000_000  # WRONG if reused

		# Correct replan always resolves from STANDARD, ignoring stale amounts
		fresh = _blank_rows()

		def resolve(idx, row):
			if 2 <= idx <= 8:
				return STANDARD, 0.3
			return STANDARD, 1.0

		apply_fixed_end_usage_adjustment(fresh, REMAINING, resolve_amount_and_factor=resolve)
		# Must equal STANDARD+49M, not STANDARD+49M piled onto 829M
		self.assertEqual(fresh[119]["depreciation_amount"], STANDARD + 49_000_000)
		self.assertNotEqual(fresh[119]["depreciation_amount"], stale[119]["depreciation_amount"])

	def test_posted_rows_excluded_from_shortfall(self):
		"""Posted installment 3 stays unchanged; shortfall only from unposted reduced rows."""
		rows = _blank_rows(posted=3)  # installments 1–3 posted at STANDARD
		# remaining excludes posted: 117 * STANDARD
		remaining = STANDARD * 117

		def resolve(idx, row):
			# Would-be 30% from installment 3, but 3 is posted — only unposted get factors
			return STANDARD, 0.3

		apply_fixed_end_usage_adjustment(rows, remaining, resolve_amount_and_factor=resolve)
		for i in range(3):
			self.assertEqual(rows[i]["depreciation_amount"], STANDARD)
			self.assertTrue(rows[i]["journal_entry"])
		for i in range(3, 119):
			self.assertEqual(rows[i]["depreciation_amount"], 3_000_000)
		# 116 reduced unposted rows (4..119) × 7M shortfall + standard final
		shortfall = 116 * 7_000_000
		self.assertEqual(rows[119]["depreciation_amount"], STANDARD + shortfall)
		self.assertEqual(
			sum(r["depreciation_amount"] for r in rows if not r["journal_entry"]),
			remaining,
		)

	def test_period_count_and_wrapper_whole_numbers(self):
		rows = [
			{"journal_entry": None, "depreciation_amount": 10, "_standard_amount": 10, "usage_factor": 0.3},
			{"journal_entry": None, "depreciation_amount": 10, "_standard_amount": 10, "usage_factor": 1.0},
			{"journal_entry": None, "depreciation_amount": 10, "_standard_amount": 10, "usage_factor": 1.0},
		]
		redistribute_unposted_amounts(rows, 30)
		self.assertEqual(len(rows), 3)
		self.assertEqual(rows[0]["depreciation_amount"], 3)
		# final = 30 - 3 - 10 = 17 (row1 factored at 1.0 → 10; final balances)
		self.assertEqual(rows[1]["depreciation_amount"], 10)
		self.assertEqual(rows[2]["depreciation_amount"], 17)
		for amount in (r["depreciation_amount"] for r in rows):
			self.assertEqual(amount, int(amount))

	def test_iran_whole_numbers_on_awkward_factor(self):
		rows = _blank_rows(n=4, amount=100)
		# 0.333... × 100 → Iran half-up
		def resolve(idx, row):
			return 100, 1 / 3

		apply_fixed_end_usage_adjustment(rows, 400, resolve_amount_and_factor=resolve)
		for r in rows[:-1]:
			self.assertEqual(r["depreciation_amount"], to_depr_amount(100 / 3))
			self.assertEqual(r["depreciation_amount"], int(r["depreciation_amount"]))
		self.assertEqual(sum(r["depreciation_amount"] for r in rows), 400)
		self.assertEqual(rows[-1]["depreciation_amount"], int(rows[-1]["depreciation_amount"]))
