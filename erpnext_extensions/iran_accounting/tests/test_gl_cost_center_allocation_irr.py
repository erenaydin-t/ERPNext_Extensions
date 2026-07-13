# Copyright (c) 2026, ERPNext Extensions contributors

import unittest
from decimal import ROUND_HALF_UP, Decimal

from erpnext_extensions.iran_accounting.domain.gl_cost_center_allocation import (
	absorb_irr_cost_center_split_residual,
)


def _irr_split(amt: float, pct: float) -> int:
	return int(Decimal(str(amt * pct / 100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


class TestGlCostCenterAllocationIrr(unittest.TestCase):
	def test_mat_ste_02920_allocation_splits_sum_exactly(self):
		amounts = [4196154, 2665425, 2326101]
		pcts = [0, 10.2, 22.9, 58.0, 8.1, 0.8]
		precision = 0
		total_loss_before = 0
		for amt in amounts:
			splits = [_irr_split(amt, p) for p in pcts]
			total_loss_before += amt - sum(splits)
		self.assertEqual(total_loss_before, 2)

		for amt in amounts:
			template = {"debit": -amt, "credit": 0}
			gle_list = []
			for i, p in enumerate(pcts):
				part = _irr_split(amt, p)
				gle_list.append(
					{
						"debit": -part,
						"credit": 0,
						"debit_in_account_currency": -part,
						"credit_in_account_currency": 0,
						"cost_center": f"CC-{i}",
					}
				)
			absorb_irr_cost_center_split_residual(gle_list, template, precision)
			self.assertEqual(sum(g["debit"] for g in gle_list), -amt)

		rebuilt = []
		for amt in amounts:
			template = {"debit": -amt, "credit": 0}
			gle_list = []
			for p in pcts:
				part = _irr_split(amt, p)
				gle_list.append(
					{
						"debit": -part,
						"credit": 0,
						"debit_in_account_currency": -part,
						"credit_in_account_currency": 0,
					}
				)
			absorb_irr_cost_center_split_residual(gle_list, template, precision)
			rebuilt.append(-sum(g["debit"] for g in gle_list))
		self.assertEqual(sum(rebuilt), sum(amounts))
