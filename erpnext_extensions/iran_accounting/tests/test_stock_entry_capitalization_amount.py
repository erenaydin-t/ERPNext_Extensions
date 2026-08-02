# Copyright (c) 2026, ERPNext Extensions contributors
"""Commit 1: Stock Entry amount ownership preserves ERPNext capitalization (rate-first IRR)."""

from __future__ import annotations

import unittest
from contextlib import contextmanager
from unittest import mock

from erpnext_extensions.iran_accounting.domain.qty_rate_amount import (
	align_stock_entry_item_amounts,
	compose_stock_entry_row_amount,
)
from erpnext_extensions.iran_accounting.domain.stock_entry_sync import stock_entry_row_amount
from erpnext_extensions.iran_accounting.tests.hardening.decimal_money import (
	amount_vs_rate_qty_residual,
	compose_amount,
	money_equal,
)
from erpnext_extensions.iran_accounting.tests.hardening.fixtures import (
	ADD_COST,
	ALT_BASIC_AMOUNT,
	ALT_BASIC_RATE,
	AMT_E,
	BASIC_A,
	BASIC_B,
	CAP_AMOUNT_A,
	CAP_AMOUNT_B,
	CAP_RESIDUAL_A,
	CAP_VAL_RATE_A,
	CAP_VAL_RATE_B,
	INT_RATE_A,
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
	QTY_A,
	QTY_B,
	RESIDUAL_E,
	STE_03516_AMOUNT,
	STE_03516_INT_RATE,
	STE_03516_QTY,
	STE_03516_RAW_RATE,
	VAL_RATE_E,
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
		mock.patch(
			"erpnext_extensions.iran_accounting.domain.stock_entry_sync.get_company_currency",
			return_value="IRR",
		),
		mock.patch(
			"erpnext_extensions.iran_accounting.domain.stock_entry_sync.is_irr_company",
			return_value=True,
		),
	):
		yield


class TestStockEntryCapitalizationAmount(unittest.TestCase):
	def test_compose_includes_additional_and_lcv(self):
		basic = BASIC_A
		row = _Row(
			basic_amount=float(basic),
			additional_cost=float(ADD_COST),
			landed_cost_voucher_amount=float(LCV_AMT),
		)
		exp = compose_amount(basic, ADD_COST, LCV_AMT, precision=IRR_PRECISION)
		money_equal(compose_stock_entry_row_amount(row, "IRR"), exp, precision=IRR_PRECISION)

	def test_align_preserves_additional_cost(self):
		row = _Row(
			qty=float(QTY_A),
			transfer_qty=float(QTY_A),
			basic_rate=float(INT_RATE_A),
			basic_amount=float(BASIC_A),
			additional_cost=float(ADD_COST),
			landed_cost_voucher_amount=0,
			amount=float(CAP_AMOUNT_A),
			valuation_rate=float(CAP_VAL_RATE_A),
		)
		doc = _Doc(doctype="Stock Entry", company="Test IRR Co", items=[row])
		with _irr_currency_patches():
			align_stock_entry_item_amounts(doc)
		money_equal(row.basic_rate, INT_RATE_A, precision=IRR_PRECISION)
		money_equal(row.basic_amount, BASIC_A, precision=IRR_PRECISION)
		money_equal(row.additional_cost, ADD_COST, precision=IRR_PRECISION)
		money_equal(row.amount, CAP_AMOUNT_A, precision=IRR_PRECISION)
		money_equal(row.valuation_rate, CAP_VAL_RATE_A, precision=IRR_PRECISION)
		money_equal(
			amount_vs_rate_qty_residual(row.amount, QTY_A, row.valuation_rate),
			CAP_RESIDUAL_A,
			precision=IRR_PRECISION,
		)

	def test_align_preserves_landed_cost(self):
		row = _Row(
			qty=float(QTY_B),
			transfer_qty=float(QTY_B),
			basic_rate=float(INT_RATE_B),
			basic_amount=float(BASIC_B),
			additional_cost=0,
			landed_cost_voucher_amount=float(LCV_AMT),
			amount=float(CAP_AMOUNT_B),
			valuation_rate=float(CAP_VAL_RATE_B),
		)
		doc = _Doc(doctype="Stock Entry", company="Test IRR Co", items=[row])
		with _irr_currency_patches():
			align_stock_entry_item_amounts(doc)
		money_equal(row.amount, CAP_AMOUNT_B, precision=IRR_PRECISION)
		money_equal(row.landed_cost_voucher_amount, LCV_AMT, precision=IRR_PRECISION)
		money_equal(row.valuation_rate, CAP_VAL_RATE_B, precision=IRR_PRECISION)

	def test_align_uses_transfer_qty_not_qty(self):
		# qty=2, conversion 5.5 → transfer_qty=11; integer rate
		row = _Row(
			qty=2,
			transfer_qty=float(QTY_B),
			basic_rate=float(ALT_BASIC_RATE),
			basic_amount=float(AMT_E),  # stale wrong
			additional_cost=0,
			landed_cost_voucher_amount=0,
			amount=float(AMT_E),
			valuation_rate=float(ALT_BASIC_RATE),
		)
		doc = _Doc(doctype="Stock Entry", company="Test IRR Co", items=[row])
		with _irr_currency_patches():
			align_stock_entry_item_amounts(doc)
		money_equal(row.basic_amount, ALT_BASIC_AMOUNT, precision=IRR_PRECISION)
		money_equal(row.amount, ALT_BASIC_AMOUNT, precision=IRR_PRECISION)
		money_equal(row.basic_rate, ALT_BASIC_RATE, precision=IRR_PRECISION)

	def test_align_zero_transfer_qty_safe(self):
		row = _Row(
			qty=0,
			transfer_qty=0,
			basic_rate=float(INT_RATE_A),
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
			basic_rate=float(INT_RATE_A),
			basic_amount=float(BASIC_A),
			additional_cost=float(ADD_COST),
			landed_cost_voucher_amount=float(LCV_AMT),
		)
		exp = compose_amount(BASIC_A, ADD_COST, LCV_AMT, precision=IRR_PRECISION)
		with _irr_currency_patches():
			money_equal(stock_entry_row_amount(row, "Test IRR Co"), exp, precision=IRR_PRECISION)

	def test_reported_manufacture_figures_rate_first(self):
		row = _Row(
			qty=float(PROD_QTY),
			transfer_qty=float(PROD_QTY),
			basic_rate=float(PROD_OUTGOING / PROD_QTY),  # fractional input → rounded
			basic_amount=float(PROD_OUTGOING),
			additional_cost=float(PROD_ADD),
			landed_cost_voucher_amount=0,
			amount=float(PROD_OUTGOING + PROD_ADD),
			valuation_rate=float((PROD_OUTGOING + PROD_ADD) / PROD_QTY),
		)
		doc = _Doc(doctype="Stock Entry", purpose="Manufacture", company="Test IRR Co", items=[row])
		with _irr_currency_patches():
			align_stock_entry_item_amounts(doc)
		money_equal(row.basic_rate, PROD_INT_RATE, precision=IRR_PRECISION)
		money_equal(row.basic_amount, PROD_BASIC, precision=IRR_PRECISION)
		money_equal(row.additional_cost, PROD_ADD, precision=IRR_PRECISION)
		money_equal(row.amount, PROD_AMOUNT, precision=IRR_PRECISION)
		money_equal(row.valuation_rate, PROD_VAL_RATE, precision=IRR_PRECISION)

	def test_mat_ste_03516_rate_first_regression(self):
		row = _Row(
			qty=float(STE_03516_QTY),
			transfer_qty=float(STE_03516_QTY),
			basic_rate=float(STE_03516_RAW_RATE),
			basic_amount=0,
			additional_cost=0,
			landed_cost_voucher_amount=0,
			amount=0,
			valuation_rate=0,
		)
		doc = _Doc(
			doctype="Stock Entry",
			purpose="Material Transfer for Manufacture",
			company="Test IRR Co",
			items=[row],
		)
		with _irr_currency_patches():
			align_stock_entry_item_amounts(doc)
		money_equal(row.basic_rate, STE_03516_INT_RATE, precision=IRR_PRECISION)
		money_equal(row.basic_amount, STE_03516_AMOUNT, precision=IRR_PRECISION)
		money_equal(row.amount, STE_03516_AMOUNT, precision=IRR_PRECISION)
		money_equal(row.valuation_rate, STE_03516_INT_RATE, precision=IRR_PRECISION)

	def test_manufacture_valuation_residual_amount_authoritative(self):
		"""amount=1371, qty=7 → valuation_rate=196, residual=-1; amount stays 1371."""
		row = _Row(
			qty=float(QTY_A),
			transfer_qty=float(QTY_A),
			basic_rate=float(INT_RATE_A),
			basic_amount=float(BASIC_A),
			additional_cost=float(AMT_E - BASIC_A),  # force amount to 1371
			landed_cost_voucher_amount=0,
			amount=float(AMT_E),
			valuation_rate=0,
		)
		doc = _Doc(doctype="Stock Entry", purpose="Manufacture", company="Test IRR Co", items=[row])
		with _irr_currency_patches():
			align_stock_entry_item_amounts(doc)
		money_equal(row.amount, AMT_E, precision=IRR_PRECISION)
		money_equal(row.valuation_rate, VAL_RATE_E, precision=IRR_PRECISION)
		money_equal(
			amount_vs_rate_qty_residual(row.amount, QTY_A, row.valuation_rate),
			RESIDUAL_E,
			precision=IRR_PRECISION,
		)


if __name__ == "__main__":
	unittest.main()
