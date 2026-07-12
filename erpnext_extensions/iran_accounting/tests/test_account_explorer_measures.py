# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

import unittest

from erpnext_extensions.iran_accounting.account_explorer.measures import (
	finalize_measures,
	measures_from_opening_period,
	sum_measure_rows,
)


class TestAccountExplorerMeasures(unittest.TestCase):
	def test_debit_balance_formula(self):
		row = measures_from_opening_period(100, 0, 50, 0)
		self.assertEqual(row["debit_balance"], 150)
		self.assertEqual(row["credit_balance"], 0)

	def test_credit_balance_formula(self):
		row = measures_from_opening_period(0, 100, 0, 20)
		self.assertEqual(row["credit_balance"], 120)
		self.assertEqual(row["debit_balance"], 0)

	def test_global_total_sum(self):
		rows = [
			finalize_measures(
				{"period_debit": 100, "period_credit": 0, "opening_debit": 0, "opening_credit": 0}
			),
			finalize_measures(
				{"period_debit": 50, "period_credit": 0, "opening_debit": 0, "opening_credit": 0}
			),
		]
		total = sum_measure_rows(rows)
		self.assertEqual(total["period_debit"], 150)
