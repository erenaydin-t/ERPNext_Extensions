# Copyright (c) 2026, ERPNext Extensions contributors

from __future__ import annotations

import unittest

from erpnext_extensions.iran_accounting.rounding import round_row_amount


class TestQtyRateRounding(unittest.TestCase):
	def test_irr_row_amount_rate_first_half_up(self):
		# Rate-first: ROUND_HALF_UP(qty × ROUND_HALF_UP(rate, 0))
		self.assertEqual(round_row_amount(1.333, 1000, "IRR"), 1333)
		# rate 1000.4 → 1000; 1.333 × 1000 → 1333 (not product-first 1334)
		self.assertEqual(round_row_amount(1.333, 1000.4, "IRR"), 1333)
		self.assertEqual(round_row_amount(1.333, 1000.5, "IRR"), 1334)  # rate → 1001

	def test_usd_row_amount_two_decimals(self):
		# Rate-first at USD precision: rate→10.56, then 1.333×10.56→14.08
		self.assertEqual(round_row_amount(1.333, 10.556, "USD"), 14.08)
