# Copyright (c) 2026, ERPNext Extensions contributors
"""Golden comparison: iran_accounting vs ERPNext ownership for Stock Entry economics (rate-first)."""

from __future__ import annotations

import unittest
from contextlib import contextmanager
from unittest import mock

from erpnext_extensions.iran_accounting.domain.qty_rate_amount import align_stock_entry_item_amounts
from erpnext_extensions.iran_accounting.manufacture_rounding import (
	align_manufacture_finished_good_residual,
)
from erpnext_extensions.iran_accounting.tests.hardening.decimal_money import money_equal
from erpnext_extensions.iran_accounting.tests.hardening.fixtures import (
	ALT_BASIC_AMOUNT,
	ALT_BASIC_RATE,
	BASIC_B,
	CAP_AMOUNT_B,
	CAP_VAL_RATE_B,
	INT_RATE_B,
	IRR_PRECISION,
	LCV_AMT,
	PROD_ADD,
	PROD_AMOUNT,
	PROD_BASIC,
	PROD_INT_RATE,
	PROD_OUTGOING,
	PROD_QTY,
	PROD_VAL_RATE,
	QTY_B,
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
	def test_manufacture_additional_cost_rate_first(self):
		# Fractional input rates → integer rate-first economics
		fg = _Row(
			qty=float(PROD_QTY),
			transfer_qty=float(PROD_QTY),
			basic_rate=float(PROD_OUTGOING / PROD_QTY),
			basic_amount=float(PROD_OUTGOING),
			additional_cost=float(PROD_ADD),
			landed_cost_voucher_amount=0,
			amount=float(PROD_OUTGOING + PROD_ADD),
			valuation_rate=float((PROD_OUTGOING + PROD_ADD) / PROD_QTY),
			s_warehouse=None,
			t_warehouse="FG",
			is_finished_item=1,
		)
		rm = _Row(
			qty=1,
			transfer_qty=1,
			basic_rate=float(PROD_BASIC),
			basic_amount=float(PROD_BASIC),
			additional_cost=0,
			landed_cost_voucher_amount=0,
			amount=float(PROD_BASIC),
			valuation_rate=float(PROD_BASIC),
			s_warehouse="RM",
			t_warehouse=None,
			is_finished_item=0,
		)
		doc = _Doc(
			doctype="Stock Entry",
			purpose="Manufacture",
			company="Test",
			items=[rm, fg],
			total_outgoing_value=float(PROD_BASIC),
			total_incoming_value=float(PROD_AMOUNT),
			value_difference=float(PROD_ADD),
		)
		with _irr():
			align_stock_entry_item_amounts(doc)
			align_manufacture_finished_good_residual(doc)

		money_equal(fg.basic_rate, PROD_INT_RATE, precision=IRR_PRECISION)
		money_equal(fg.basic_amount, PROD_BASIC, precision=IRR_PRECISION)
		money_equal(fg.amount, PROD_AMOUNT, precision=IRR_PRECISION)
		money_equal(fg.valuation_rate, PROD_VAL_RATE, precision=IRR_PRECISION)
		money_equal(doc.value_difference, PROD_ADD, precision=IRR_PRECISION)

	def test_lcv_rate_first(self):
		row = _Row(
			qty=float(QTY_B),
			transfer_qty=float(QTY_B),
			basic_rate=float(INT_RATE_B),
			basic_amount=float(BASIC_B),
			additional_cost=0,
			landed_cost_voucher_amount=float(LCV_AMT),
			amount=float(CAP_AMOUNT_B),
			valuation_rate=float(CAP_VAL_RATE_B),
			s_warehouse=None,
			t_warehouse="S",
			is_finished_item=0,
		)
		doc = _Doc(doctype="Stock Entry", purpose="Material Receipt", company="Test", items=[row])
		with _irr():
			align_stock_entry_item_amounts(doc)
		money_equal(row.amount, CAP_AMOUNT_B, precision=IRR_PRECISION)
		money_equal(row.landed_cost_voucher_amount, LCV_AMT, precision=IRR_PRECISION)
		money_equal(row.valuation_rate, CAP_VAL_RATE_B, precision=IRR_PRECISION)

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
		row = _Row(
			qty=2,
			transfer_qty=float(QTY_B),
			basic_rate=float(ALT_BASIC_RATE),
			basic_amount=200,
			additional_cost=0,
			landed_cost_voucher_amount=0,
			amount=200,
			valuation_rate=float(ALT_BASIC_RATE),
			s_warehouse=None,
			t_warehouse="S",
			is_finished_item=0,
		)
		doc = _Doc(doctype="Stock Entry", purpose="Material Receipt", company="Test", items=[row])
		with _irr():
			align_stock_entry_item_amounts(doc)
		money_equal(row.basic_amount, ALT_BASIC_AMOUNT, precision=IRR_PRECISION)
		money_equal(row.amount, ALT_BASIC_AMOUNT, precision=IRR_PRECISION)
		money_equal(row.basic_rate, ALT_BASIC_RATE, precision=IRR_PRECISION)


if __name__ == "__main__":
	unittest.main()
