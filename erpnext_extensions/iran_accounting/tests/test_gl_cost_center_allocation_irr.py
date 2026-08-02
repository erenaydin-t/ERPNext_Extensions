# Copyright (c) 2026, ERPNext Extensions contributors

import unittest
from decimal import ROUND_HALF_UP, Decimal
from unittest import mock

from erpnext_extensions.iran_accounting.domain.gl_cost_center_allocation import (
	absorb_irr_cost_center_split_residual,
	distribute_gl_based_on_cost_center_allocation_irr,
)
from erpnext_extensions.iran_accounting.domain.irr_rounding_residual import (
	IRR_RATE_ROUNDING_RESIDUAL_MARKER,
	IRR_RATE_ROUNDING_RESIDUAL_REMARK,
)


def _irr_split(amt: float, pct: float) -> int:
	return int(Decimal(str(amt * pct / 100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def frappe_dict(d: dict):
	class _D(dict):
		def __getattr__(self, k):
			try:
				return self[k]
			except KeyError as e:
				raise AttributeError(k) from e

		__setattr__ = dict.__setitem__

	return _D(d)


def _cached_value_side_effect(company, ro_account, ro_cc):
	def _inner(doctype, name, field=None, *args, **kwargs):
		if doctype == "Company" and name == company:
			if field == "default_currency":
				return "IRR"
			if field == "round_off_account":
				return ro_account
			if isinstance(field, (list, tuple)) and list(field) == [
				"round_off_account",
				"round_off_cost_center",
			]:
				return (ro_account, ro_cc)
		return None

	return _inner


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

	def test_irr_residual_round_off_excluded_from_cca(self):
		"""IRR residual Round Off keeps Company.round_off_cost_center; ops rows still split."""
		company = "Test IRR Co"
		ro_account = "Round Off - T"
		ro_cc = "Main - T"
		child_a, child_b = "FA383-CC-A - T", "FA383-CC-B - T"

		gl_map = [
			frappe_dict(
				{
					"company": company,
					"posting_date": "2026-08-28",
					"account": "Stock In Hand - T",
					"cost_center": ro_cc,
					"debit": 1000,
					"credit": 0,
					"debit_in_account_currency": 1000,
					"credit_in_account_currency": 0,
					"remarks": "Accounting Entry for Stock",
				}
			),
			frappe_dict(
				{
					"company": company,
					"posting_date": "2026-08-28",
					"account": "Stock Adjustment - T",
					"cost_center": ro_cc,
					"debit": 0,
					"credit": 999,
					"debit_in_account_currency": 0,
					"credit_in_account_currency": 999,
					"remarks": "Accounting Entry for Stock",
				}
			),
			frappe_dict(
				{
					"company": company,
					"posting_date": "2026-08-28",
					"account": ro_account,
					"cost_center": "WRONG-CC",  # must be overwritten to Company CC
					IRR_RATE_ROUNDING_RESIDUAL_MARKER: 1,
					"debit": 0,
					"credit": 1,
					"debit_in_account_currency": 0,
					"credit_in_account_currency": 1,
					"remarks": f"{IRR_RATE_ROUNDING_RESIDUAL_REMARK}: row 1",
				}
			),
		]

		def fake_alloc(_company, _posting_date, cost_center):
			if cost_center == ro_cc:
				return [(child_a, 60), (child_b, 40)]
			return None

		with (
			mock.patch(
				"erpnext_extensions.iran_accounting.domain.gl_cost_center_allocation.is_irr_company",
				return_value=True,
			),
			mock.patch(
				"erpnext_extensions.iran_accounting.domain.gl_cost_center_allocation.get_currency_precision",
				return_value=0,
			),
			mock.patch(
				"frappe.get_cached_value",
				side_effect=_cached_value_side_effect(company, ro_account, ro_cc),
			),
			mock.patch(
				"erpnext.accounts.general_ledger.get_cost_center_allocation_data",
				side_effect=fake_alloc,
			),
			mock.patch(
				"erpnext.accounts.general_ledger.validate_expense_against_budget",
				return_value=None,
			),
			mock.patch(
				"erpnext_extensions.iran_accounting.domain.irr_rounding_residual.resolve_company_round_off",
				return_value={"account": ro_account, "cost_center": ro_cc},
			),
			mock.patch(
				"erpnext_extensions.iran_accounting.domain.irr_rounding_residual.validate_round_off_configuration",
				return_value=None,
			),
		):
			out = distribute_gl_based_on_cost_center_allocation_irr(gl_map, precision=0)

		ro_rows = [r for r in out if r.get(IRR_RATE_ROUNDING_RESIDUAL_MARKER)]
		self.assertEqual(len(ro_rows), 1)
		self.assertEqual(ro_rows[0]["account"], ro_account)
		self.assertEqual(ro_rows[0]["cost_center"], ro_cc)

		stock_rows = [r for r in out if r.get("account") == "Stock In Hand - T"]
		self.assertEqual(len(stock_rows), 2)
		self.assertEqual(sum(r["debit"] for r in stock_rows), 1000)
		self.assertEqual({r["cost_center"] for r in stock_rows}, {child_a, child_b})
