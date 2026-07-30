# Copyright (c) 2026, ERPNext Extensions contributors
"""Commit 5: repost must preserve Stock Entry capitalization."""

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
	valuation_from_amount,
)
from erpnext_extensions.iran_accounting.tests.hardening.fixtures import (
	ADD_COST,
	AMT_A,
	IRR_PRECISION,
	LCV_AMT,
	PROD_ADD,
	PROD_FG,
	PROD_OUTGOING,
	PROD_QTY,
	QTY_A,
	RATE_A,
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
		outgoing = float(PROD_OUTGOING)
		add_cost = float(PROD_ADD)
		expected = float(PROD_FG)
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
			basic_rate=outgoing / qty,
			basic_amount=outgoing,
			additional_cost=add_cost,
			landed_cost_voucher_amount=0,
			amount=expected,
			valuation_rate=expected / qty,
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
		money_equal(fg.amount, PROD_FG, precision=IRR_PRECISION)
		money_equal(fg.additional_cost, PROD_ADD, precision=IRR_PRECISION)
		money_equal(doc.value_difference, PROD_ADD, precision=IRR_PRECISION)

	def test_reconcile_path_preserves_lcv(self):
		amount = compose_amount(AMT_A, 0, LCV_AMT, precision=IRR_PRECISION)
		row = _Row(
			qty=float(QTY_A),
			transfer_qty=float(QTY_A),
			basic_rate=float(RATE_A),
			basic_amount=float(AMT_A),
			additional_cost=0,
			landed_cost_voucher_amount=float(LCV_AMT),
			amount=float(amount),
			valuation_rate=float(valuation_from_amount(amount, QTY_A)),
			s_warehouse=None,
			t_warehouse="Stores",
			is_finished_item=0,
		)
		doc = _Doc(doctype="Stock Entry", purpose="Material Receipt", company="Test", items=[row])
		with _irr():
			align_stock_entry_item_amounts(doc)
		money_equal(row.amount, amount, precision=IRR_PRECISION)
		money_equal(row.landed_cost_voucher_amount, LCV_AMT, precision=IRR_PRECISION)

	def test_idempotent_double_align(self):
		amount = compose_amount(AMT_A, ADD_COST, LCV_AMT, precision=IRR_PRECISION)
		row = _Row(
			qty=float(QTY_A),
			transfer_qty=float(QTY_A),
			basic_rate=float(RATE_A),
			basic_amount=float(AMT_A),
			additional_cost=float(ADD_COST),
			landed_cost_voucher_amount=float(LCV_AMT),
			amount=float(amount),
			valuation_rate=float(valuation_from_amount(amount, QTY_A)),
			s_warehouse=None,
			t_warehouse="Stores",
			is_finished_item=0,
		)
		doc = _Doc(doctype="Stock Entry", purpose="Material Receipt", company="Test", items=[row])
		with _irr():
			align_stock_entry_item_amounts(doc)
			a1 = row.amount
			align_stock_entry_item_amounts(doc)
			a2 = row.amount
		money_equal(a1, amount, precision=IRR_PRECISION)
		money_equal(a2, amount, precision=IRR_PRECISION)


if __name__ == "__main__":
	unittest.main()
