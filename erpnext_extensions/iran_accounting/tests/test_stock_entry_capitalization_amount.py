# Copyright (c) 2026, ERPNext Extensions contributors
"""Commit 1: Stock Entry amount ownership preserves ERPNext capitalization.

Fixtures use non-trivial amounts/qtys that force repeating valuation rates.
"""

from __future__ import annotations

import unittest
from contextlib import contextmanager
from decimal import Decimal
from unittest import mock

from erpnext_extensions.iran_accounting.domain.qty_rate_amount import (
	align_stock_entry_item_amounts,
	compose_stock_entry_row_amount,
)
from erpnext_extensions.iran_accounting.domain.stock_entry_sync import stock_entry_row_amount
from erpnext_extensions.iran_accounting.tests.hardening.decimal_money import (
	D,
	compose_amount,
	money_equal,
	rate_equal,
	valuation_from_amount,
)
from erpnext_extensions.iran_accounting.tests.hardening.fixtures import (
	ADD_COST,
	AMT_A,
	AMT_B,
	AMT_E,
	IRR_PRECISION,
	LCV_AMT,
	PROD_ADD,
	PROD_FG,
	PROD_OUTGOING,
	PROD_QTY,
	QTY_A,
	QTY_B,
	RATE_A,
	RATE_B,
)


class _Row:
	def __init__(self, **fields):
		self.__dict__.update(fields)

	def get(self, key, default=None):
		return self.__dict__.get(key, default)

	def set(self, key, value):
		self.__dict__[key] = value


class _Doc:
	def __init__(self, **fields):
		self.__dict__.update(fields)

	def get(self, key, default=None):
		return self.__dict__.get(key, default)


@contextmanager
def _irr_currency_patches():
	with (
		mock.patch(
			"erpnext_extensions.iran_accounting.domain.currency.is_irr_company",
			return_value=True,
		),
		mock.patch(
			"erpnext_extensions.iran_accounting.domain.currency.get_company_currency",
			return_value="IRR",
		),
	):
		yield


class TestStockEntryCapitalizationAmount(unittest.TestCase):
	def test_compose_includes_additional_and_lcv(self):
		basic = AMT_A
		row = _Row(basic_amount=float(basic), additional_cost=float(ADD_COST), landed_cost_voucher_amount=float(LCV_AMT))
		exp = compose_amount(basic, ADD_COST, LCV_AMT, precision=IRR_PRECISION)
		money_equal(compose_stock_entry_row_amount(row, "IRR"), exp, precision=IRR_PRECISION)

	def test_align_preserves_additional_cost(self):
		basic = AMT_A
		qty = QTY_A
		amount = compose_amount(basic, ADD_COST, 0, precision=IRR_PRECISION)
		row = _Row(
			qty=float(qty),
			transfer_qty=float(qty),
			basic_rate=float(RATE_A),
			basic_amount=float(basic),
			additional_cost=float(ADD_COST),
			landed_cost_voucher_amount=0,
			amount=float(amount),
			valuation_rate=float(valuation_from_amount(amount, qty)),
		)
		doc = _Doc(doctype="Stock Entry", company="Test IRR Co", items=[row])
		with _irr_currency_patches():
			align_stock_entry_item_amounts(doc)
		money_equal(row.basic_amount, basic, precision=IRR_PRECISION)
		money_equal(row.additional_cost, ADD_COST, precision=IRR_PRECISION)
		money_equal(row.amount, amount, precision=IRR_PRECISION)
		rate_equal(row.valuation_rate, valuation_from_amount(amount, qty), places=9)

	def test_align_preserves_landed_cost(self):
		basic = AMT_B
		qty = QTY_B
		amount = compose_amount(basic, 0, LCV_AMT, precision=IRR_PRECISION)
		row = _Row(
			qty=float(qty),
			transfer_qty=float(qty),
			basic_rate=float(RATE_B),
			basic_amount=float(basic),
			additional_cost=0,
			landed_cost_voucher_amount=float(LCV_AMT),
			amount=float(amount),
			valuation_rate=float(valuation_from_amount(amount, qty)),
		)
		doc = _Doc(doctype="Stock Entry", company="Test IRR Co", items=[row])
		with _irr_currency_patches():
			align_stock_entry_item_amounts(doc)
		money_equal(row.amount, amount, precision=IRR_PRECISION)
		money_equal(row.landed_cost_voucher_amount, LCV_AMT, precision=IRR_PRECISION)
		rate_equal(row.valuation_rate, valuation_from_amount(amount, qty), places=9)

	def test_align_uses_transfer_qty_not_qty(self):
		# qty=2, conversion 5.5 → transfer_qty=11; rate = 1237/11
		row = _Row(
			qty=2,
			transfer_qty=float(QTY_B),
			basic_rate=float(RATE_B),
			basic_amount=float(AMT_E),  # stale wrong (qty-based)
			additional_cost=0,
			landed_cost_voucher_amount=0,
			amount=float(AMT_E),
			valuation_rate=float(RATE_B),
		)
		doc = _Doc(doctype="Stock Entry", company="Test IRR Co", items=[row])
		with _irr_currency_patches():
			align_stock_entry_item_amounts(doc)
		money_equal(row.basic_amount, AMT_B, precision=IRR_PRECISION)
		money_equal(row.amount, AMT_B, precision=IRR_PRECISION)
		rate_equal(row.valuation_rate, RATE_B, places=9)

	def test_align_zero_transfer_qty_safe(self):
		row = _Row(
			qty=0,
			transfer_qty=0,
			basic_rate=float(RATE_A),
			basic_amount=0,
			additional_cost=0,
			landed_cost_voucher_amount=0,
			amount=0,
			valuation_rate=0,
		)
		doc = _Doc(doctype="Stock Entry", company="Test IRR Co", items=[row])
		with _irr_currency_patches():
			align_stock_entry_item_amounts(doc)
		money_equal(row.amount, 0, precision=IRR_PRECISION)

	def test_stock_entry_row_amount_fallback_composes_capitalization(self):
		row = _Row(
			amount=None,
			transfer_qty=float(QTY_A),
			basic_rate=float(RATE_A),
			basic_amount=float(AMT_A),
			additional_cost=float(ADD_COST),
			landed_cost_voucher_amount=float(LCV_AMT),
		)
		exp = compose_amount(AMT_A, ADD_COST, LCV_AMT, precision=IRR_PRECISION)
		with _irr_currency_patches():
			money_equal(stock_entry_row_amount(row, "Test IRR Co"), exp, precision=IRR_PRECISION)

	def test_reported_manufacture_figures_preserved(self):
		qty = PROD_QTY
		row = _Row(
			qty=float(qty),
			transfer_qty=float(qty),
			basic_rate=float(PROD_OUTGOING / qty),
			basic_amount=float(PROD_OUTGOING),
			additional_cost=float(PROD_ADD),
			landed_cost_voucher_amount=0,
			amount=float(PROD_FG),
			valuation_rate=float(PROD_FG / qty),
		)
		doc = _Doc(doctype="Stock Entry", purpose="Manufacture", company="Test IRR Co", items=[row])
		with _irr_currency_patches():
			align_stock_entry_item_amounts(doc)
		money_equal(row.amount, PROD_FG, precision=IRR_PRECISION)
		money_equal(row.additional_cost, PROD_ADD, precision=IRR_PRECISION)
		rate_equal(row.valuation_rate, PROD_FG / qty, places=9)


if __name__ == "__main__":
	unittest.main()
