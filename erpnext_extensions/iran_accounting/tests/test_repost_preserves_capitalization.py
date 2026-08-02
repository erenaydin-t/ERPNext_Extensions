# Copyright (c) 2026, ERPNext Extensions contributors
"""Commit 5: repost must preserve Stock Entry capitalization (rate-first)."""

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
	ADD_COST,
	BASIC_A,
	CAP_AMOUNT_A,
	CAP_AMOUNT_B,
	CAP_VAL_RATE_A,
	INT_RATE_A,
	INT_RATE_B,
	IRR_PRECISION,
	LCV_AMT,
	PROD_ADD,
	PROD_AMOUNT,
	PROD_BASIC,
	PROD_OUTGOING,
	PROD_QTY,
	QTY_A,
	BASIC_B,
	QTY_B,
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
		mock.patch(
			"erpnext_extensions.iran_accounting.domain.ledger_rounding.is_irr_company",
			return_value=True,
		),
		mock.patch(
			"erpnext_extensions.iran_accounting.domain.ledger_rounding.get_company_currency",
			return_value="IRR",
		),
	):
		yield


class TestRepostPreservesCapitalization(unittest.TestCase):
	def test_reconcile_path_preserves_additional_cost(self):
		qty = float(PROD_QTY)
		outgoing = float(PROD_BASIC)
		add_cost = float(PROD_ADD)
		expected = float(PROD_AMOUNT)
		rm = _Row(
			qty=1,
			transfer_qty=1,
			basic_rate=outgoing,
			basic_amount=outgoing,
			additional_cost=0,
			landed_cost_voucher_amount=0,
			amount=outgoing,
			valuation_rate=outgoing,
			s_warehouse="RM",
			t_warehouse=None,
			is_finished_item=0,
		)
		fg = _Row(
			qty=qty,
			transfer_qty=qty,
			basic_rate=float(PROD_OUTGOING / PROD_QTY),
			basic_amount=float(PROD_OUTGOING),
			additional_cost=add_cost,
			landed_cost_voucher_amount=0,
			amount=float(PROD_OUTGOING + PROD_ADD),
			valuation_rate=float((PROD_OUTGOING + PROD_ADD) / PROD_QTY),
			s_warehouse=None,
			t_warehouse="FG",
			is_finished_item=1,
		)
		doc = _Doc(
			doctype="Stock Entry",
			purpose="Manufacture",
			company="Test",
			items=[rm, fg],
			total_outgoing_value=outgoing,
			total_incoming_value=expected,
			value_difference=add_cost,
		)
		with _irr():
			align_stock_entry_item_amounts(doc)
			align_manufacture_finished_good_residual(doc)
		money_equal(fg.amount, PROD_AMOUNT, precision=IRR_PRECISION)
		money_equal(fg.additional_cost, PROD_ADD, precision=IRR_PRECISION)
		money_equal(doc.value_difference, PROD_ADD, precision=IRR_PRECISION)

	def test_reconcile_path_preserves_lcv(self):
		row = _Row(
			qty=float(QTY_B),
			transfer_qty=float(QTY_B),
			basic_rate=float(INT_RATE_B),
			basic_amount=float(BASIC_B),
			additional_cost=0,
			landed_cost_voucher_amount=float(LCV_AMT),
			amount=float(CAP_AMOUNT_B),
			valuation_rate=0,
			s_warehouse=None,
			t_warehouse="Stores",
			is_finished_item=0,
		)
		doc = _Doc(doctype="Stock Entry", purpose="Material Receipt", company="Test", items=[row])
		with _irr():
			align_stock_entry_item_amounts(doc)
		money_equal(row.amount, CAP_AMOUNT_B, precision=IRR_PRECISION)
		money_equal(row.landed_cost_voucher_amount, LCV_AMT, precision=IRR_PRECISION)

	def test_idempotent_double_align(self):
		row = _Row(
			qty=float(QTY_A),
			transfer_qty=float(QTY_A),
			basic_rate=float(INT_RATE_A),
			basic_amount=float(BASIC_A),
			additional_cost=float(ADD_COST),
			landed_cost_voucher_amount=float(LCV_AMT),
			amount=float(CAP_AMOUNT_A + LCV_AMT),
			valuation_rate=float(CAP_VAL_RATE_A),
			s_warehouse=None,
			t_warehouse="Stores",
			is_finished_item=0,
		)
		doc = _Doc(doctype="Stock Entry", purpose="Material Receipt", company="Test", items=[row])
		with _irr():
			align_stock_entry_item_amounts(doc)
			a1 = row.amount
			v1 = row.valuation_rate
			align_stock_entry_item_amounts(doc)
			a2 = row.amount
			v2 = row.valuation_rate
		money_equal(a1, a2, precision=IRR_PRECISION)
		money_equal(v1, v2, precision=IRR_PRECISION)
		money_equal(row.basic_rate, INT_RATE_A, precision=IRR_PRECISION)


if __name__ == "__main__":
	unittest.main()
