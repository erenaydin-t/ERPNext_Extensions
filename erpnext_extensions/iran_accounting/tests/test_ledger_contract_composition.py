# Copyright (c) 2026, ERPNext Extensions contributors

from __future__ import annotations

import unittest
from unittest import mock

from erpnext_extensions.iran_accounting.domain.stock_entry_ledger_contract import (
	_assert_row_composition,
)
from erpnext_extensions.iran_accounting.tests.hardening.fixtures import (
	ADD_COST,
	BASIC_A,
	CAP_AMOUNT_A,
	CAP_VAL_RATE_A,
	INT_RATE_A,
	QTY_A,
)


class _Row:
	def __init__(self, **kw):
		self.__dict__.update(kw)

	def get(self, k, default=None):
		return self.__dict__.get(k, default)


class _Doc:
	def __init__(self, **kw):
		self.__dict__.update(kw)

	def get(self, k, default=None):
		return self.__dict__.get(k, default)


class TestLedgerContractComposition(unittest.TestCase):
	def test_composition_pass_with_additional_cost(self):
		doc = _Doc(
			doctype="Stock Entry",
			name="STE-1",
			items=[
				_Row(
					idx=1,
					name="row1",
					item_code="FG",
					transfer_qty=float(QTY_A),
					qty=float(QTY_A),
					basic_rate=float(INT_RATE_A),
					basic_amount=float(BASIC_A),
					additional_cost=float(ADD_COST),
					landed_cost_voucher_amount=0,
					amount=float(CAP_AMOUNT_A),
					valuation_rate=float(CAP_VAL_RATE_A),
				)
			],
		)
		with (
			mock.patch(
				"erpnext_extensions.iran_accounting.domain.stock_entry_ledger_contract.get_company_currency",
				return_value="IRR",
			),
			mock.patch(
				"erpnext_extensions.iran_accounting.domain.stock_entry_ledger_contract.get_currency_precision",
				return_value=0,
			),
			mock.patch(
				"erpnext_extensions.iran_accounting.domain.currency.get_company_currency",
				return_value="IRR",
			),
		):
			failures = _assert_row_composition(doc, "Test")
		self.assertEqual(failures, [])

	def test_composition_fails_when_amount_strips_add_cost(self):
		doc = _Doc(
			doctype="Stock Entry",
			name="STE-2",
			items=[
				_Row(
					idx=1,
					name="row1",
					item_code="FG",
					transfer_qty=float(QTY_A),
					qty=float(QTY_A),
					basic_rate=float(INT_RATE_A),
					basic_amount=float(BASIC_A),
					additional_cost=float(ADD_COST),
					landed_cost_voucher_amount=0,
					amount=float(BASIC_A),  # stripped capitalization
					valuation_rate=float(INT_RATE_A),
				)
			],
		)
		with (
			mock.patch(
				"erpnext_extensions.iran_accounting.domain.stock_entry_ledger_contract.get_company_currency",
				return_value="IRR",
			),
			mock.patch(
				"erpnext_extensions.iran_accounting.domain.stock_entry_ledger_contract.get_currency_precision",
				return_value=0,
			),
			mock.patch(
				"erpnext_extensions.iran_accounting.domain.currency.get_company_currency",
				return_value="IRR",
			),
		):
			failures = _assert_row_composition(doc, "Test")
		self.assertTrue(any("additional_cost" in f for f in failures))

	def test_composition_fails_on_fractional_basic_rate(self):
		doc = _Doc(
			doctype="Stock Entry",
			name="STE-3",
			items=[
				_Row(
					idx=1,
					name="row1",
					item_code="FG",
					transfer_qty=float(QTY_A),
					qty=float(QTY_A),
					basic_rate=176.285714,
					basic_amount=float(BASIC_A),
					additional_cost=0,
					landed_cost_voucher_amount=0,
					amount=float(BASIC_A),
					valuation_rate=float(INT_RATE_A),
				)
			],
		)
		with (
			mock.patch(
				"erpnext_extensions.iran_accounting.domain.stock_entry_ledger_contract.get_company_currency",
				return_value="IRR",
			),
			mock.patch(
				"erpnext_extensions.iran_accounting.domain.stock_entry_ledger_contract.get_currency_precision",
				return_value=0,
			),
			mock.patch(
				"erpnext_extensions.iran_accounting.domain.currency.get_company_currency",
				return_value="IRR",
			),
		):
			failures = _assert_row_composition(doc, "Test")
		self.assertTrue(any("basic_rate" in f for f in failures))


if __name__ == "__main__":
	unittest.main()
