# Copyright (c) 2026, ERPNext Extensions contributors

from __future__ import annotations

import unittest

from erpnext_extensions.iran_accounting.rounding import round_row_amount


class TestQtyRateRounding(unittest.TestCase):
	def test_irr_row_amount_half_up(self):
		self.assertEqual(round_row_amount(1.333, 1000, "IRR"), 1333)
		self.assertEqual(round_row_amount(1.333, 1000.4, "IRR"), 1334)

	def test_usd_row_amount_two_decimals(self):
		self.assertEqual(round_row_amount(1.333, 10.556, "USD"), 14.07)
