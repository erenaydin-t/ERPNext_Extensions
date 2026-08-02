# Copyright (c) 2026, ERPNext Extensions contributors
"""Unit tests: IRR rate-first ROUND_HALF_UP contract (no DB)."""

from __future__ import annotations

import unittest

from erpnext_extensions.iran_accounting.core.rounding import (
	rate_qty_amount_residual,
	round_currency,
	round_rate,
	round_row_amount,
)
from erpnext_extensions.iran_accounting.tests.hardening.fixtures import (
	AMT_E,
	QTY_A,
	RESIDUAL_E,
	STE_03516_AMOUNT,
	STE_03516_DELTA,
	STE_03516_INT_RATE,
	STE_03516_LEGACY_AMOUNT,
	STE_03516_QTY,
	STE_03516_RAW_RATE,
	VAL_RATE_E,
)


class TestIRRRateFirstRounding(unittest.TestCase):
	def test_half_up_boundary(self):
		self.assertEqual(round_rate(1.5, 0), 2)
		self.assertEqual(round_rate(2.5, 0), 3)
		self.assertEqual(round_rate(2207006.5, 0), 2207007)
		self.assertEqual(round_rate(2207006.162248996, 0), 2207006)

	def test_rate_first_vs_product_first(self):
		# Product-first (bug): round(qty × fractional_rate)
		legacy = round_currency(float(STE_03516_QTY) * float(STE_03516_RAW_RATE), 0)
		self.assertEqual(legacy, int(STE_03516_LEGACY_AMOUNT))
		# Rate-first (contract)
		contract = round_row_amount(STE_03516_QTY, STE_03516_RAW_RATE, 0)
		self.assertEqual(contract, int(STE_03516_AMOUNT))
		self.assertEqual(int(STE_03516_DELTA), legacy - contract)

	def test_fractional_qty_integer_rate(self):
		qty = 1.333
		rate = 1000.4
		# Rate first: rate→1000, then 1.333×1000 → 1333
		self.assertEqual(round_row_amount(qty, rate, 0), 1333)
		# Product-first would be round(1.333×1000.4)=1334
		self.assertEqual(round_currency(qty * rate, 0), 1334)

	def test_valuation_residual_amount_authoritative(self):
		self.assertEqual(round_rate(float(AMT_E) / float(QTY_A), 0), int(VAL_RATE_E))
		residual = rate_qty_amount_residual(AMT_E, QTY_A, VAL_RATE_E, 0)
		self.assertEqual(residual, int(RESIDUAL_E))
		# Must not force amount to rate×qty
		self.assertNotEqual(int(VAL_RATE_E) * int(QTY_A), int(AMT_E))

	def test_residual_uses_rounded_product_not_half_float(self):
		# qty×rate ends in .5; amount already equals ROUND_HALF_UP(product).
		qty, rate, amount = 30292.02, 5325, 161305007
		self.assertEqual(round_row_amount(qty, rate, 0), amount)
		self.assertEqual(rate_qty_amount_residual(amount, qty, rate, 0), 0)


if __name__ == "__main__":
	unittest.main()
