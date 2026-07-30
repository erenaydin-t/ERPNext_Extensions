# Copyright (c) 2026, ERPNext Extensions contributors
"""Golden comparison: iran_accounting vs ERPNext ownership for Stock Entry economics."""

from __future__ import annotations

import unittest
from contextlib import contextmanager
from unittest import mock

from erpnext_extensions.iran_accounting.domain.qty_rate_amount import align_stock_entry_item_amounts
from erpnext_extensions.iran_accounting.manufacture_rounding import (
	align_manufacture_finished_good_residual,
)
from erpnext_extensions.iran_accounting.tests.hardening.decimal_money import (
	compose_amount,
	money_equal,
	rate_equal,
	valuation_from_amount,
)
from erpnext_extensions.iran_accounting.tests.hardening.fixtures import (
	AMT_B,
	IRR_PRECISION,
	LCV_AMT,
	PROD_ADD,
	PROD_FG,
	PROD_OUTGOING,
	PROD_QTY,
	QTY_B,
	RATE_B,
)
from erpnext_extensions.iran_accounting.zero_value_transfer import (
	ZERO_VALUE_TRANSFER_STOCK_ENTRY_PURPOSES,
	_should_force_balanced_transfer_gl,
)


class _Row:
	def __init__(self, **kw):
		self.__dict__.update(kw)

	def get(self, k, default=None):
		return self.__dict__.get(k, default)

	def set(self, k, v):
		self.__dict__[k] = v


class _Doc:
	def __init__(self, **kw):
		self.__dict__.update(kw)

	def get(self, k, default=None):
		return self.__dict__.get(k, default)


def _erpnext_compose(basic_amount, additional_cost, landed_cost):
	return compose_amount(basic_amount, additional_cost, landed_cost, precision=IRR_PRECISION)


@contextmanager
def _irr():
	with (
		mock.patch(
			"erpnext_extensions.iran_accounting.domain.currency.is_irr_company",
			return_value=True,
		),
		mock.patch(
			"erpnext_extensions.iran_accounting.domain.currency.get_company_currency",
			return_value="IRR",
		),
		mock.patch(
			"erpnext_extensions.iran_accounting.manufacture_rounding.is_irr_company",
			return_value=True,
		),
		mock.patch(
			"erpnext_extensions.iran_accounting.manufacture_rounding.get_company_currency",
			return_value="IRR",
		),
		mock.patch(
			"erpnext_extensions.iran_accounting.manufacture_rounding.get_currency_precision",
			return_value=0,
		),
	):
		yield


class TestGoldenComparisonCapitalization(unittest.TestCase):
	def test_manufacture_additional_cost_matches_erpnext_economics(self):
		basic = PROD_OUTGOING
		add = PROD_ADD
		qty = PROD_QTY
		erpnext_amount = _erpnext_compose(basic, add, 0)
		erpnext_rate = valuation_from_amount(erpnext_amount, qty)

		fg = _Row(
			qty=float(qty),
			transfer_qty=float(qty),
			basic_rate=float(basic / qty),
			basic_amount=float(basic),
			additional_cost=float(add),
			landed_cost_voucher_amount=0,
			amount=float(erpnext_amount),
			valuation_rate=float(erpnext_rate),
			s_warehouse=None,
			t_warehouse="FG",
			is_finished_item=1,
		)
		rm = _Row(
			qty=1,
			transfer_qty=1,
			basic_rate=float(basic),
			basic_amount=float(basic),
			additional_cost=0,
			landed_cost_voucher_amount=0,
			amount=float(basic),
			valuation_rate=float(basic),
			s_warehouse="RM",
			t_warehouse=None,
			is_finished_item=0,
		)
		doc = _Doc(
			doctype="Stock Entry",
			purpose="Manufacture",
			company="Test",
			items=[rm, fg],
			total_outgoing_value=float(basic),
			total_incoming_value=float(erpnext_amount),
			value_difference=float(add),
		)
		with _irr():
			align_stock_entry_item_amounts(doc)
			align_manufacture_finished_good_residual(doc)

		money_equal(fg.amount, erpnext_amount, precision=IRR_PRECISION)
		rate_equal(fg.valuation_rate, erpnext_rate, places=9)
		money_equal(doc.value_difference, add, precision=IRR_PRECISION)

	def test_lcv_matches_erpnext_economics(self):
		basic = AMT_B
		lcv = LCV_AMT
		qty = QTY_B
		erpnext_amount = _erpnext_compose(basic, 0, lcv)
		row = _Row(
			qty=float(qty),
			transfer_qty=float(qty),
			basic_rate=float(RATE_B),
			basic_amount=float(basic),
			additional_cost=0,
			landed_cost_voucher_amount=float(lcv),
			amount=float(erpnext_amount),
			valuation_rate=float(valuation_from_amount(erpnext_amount, qty)),
			s_warehouse=None,
			t_warehouse="S",
			is_finished_item=0,
		)
		doc = _Doc(doctype="Stock Entry", purpose="Material Receipt", company="Test", items=[row])
		with _irr():
			align_stock_entry_item_amounts(doc)
		money_equal(row.amount, erpnext_amount, precision=IRR_PRECISION)
		money_equal(row.landed_cost_voucher_amount, lcv, precision=IRR_PRECISION)

	def test_zero_value_transfer_uses_iran_shape_not_core_builder(self):
		self.assertIn("Material Transfer", ZERO_VALUE_TRANSFER_STOCK_ENTRY_PURPOSES)

		class Doc:
			doctype = "Stock Entry"
			purpose = "Material Transfer"
			company = "Test"
			total_incoming_value = 1234
			total_outgoing_value = 1234
			value_difference = 0

			def set_total_incoming_outgoing_value(self):
				pass

		self.assertTrue(_should_force_balanced_transfer_gl(Doc(), 0))

	def test_conversion_factor_uses_transfer_qty(self):
		# qty=2 alt UOM, transfer_qty=11 stock UOM, rate = 1237/11
		row = _Row(
			qty=2,
			transfer_qty=float(QTY_B),
			basic_rate=float(RATE_B),
			basic_amount=200,  # stale qty-based
			additional_cost=0,
			landed_cost_voucher_amount=0,
			amount=200,
			valuation_rate=float(RATE_B),
			s_warehouse=None,
			t_warehouse="S",
			is_finished_item=0,
		)
		doc = _Doc(doctype="Stock Entry", purpose="Material Receipt", company="Test", items=[row])
		with _irr():
			align_stock_entry_item_amounts(doc)
		money_equal(row.basic_amount, AMT_B, precision=IRR_PRECISION)
		money_equal(row.amount, AMT_B, precision=IRR_PRECISION)
		rate_equal(row.valuation_rate, RATE_B, places=9)


if __name__ == "__main__":
	unittest.main()
