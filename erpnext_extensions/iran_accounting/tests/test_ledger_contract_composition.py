# Copyright (c) 2026, ERPNext Extensions contributors

from __future__ import annotations

import unittest
from unittest import mock

from frappe.utils import flt

from erpnext_extensions.iran_accounting.domain.stock_entry_ledger_contract import (
	_assert_row_composition,
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
					transfer_qty=10,
					qty=10,
					basic_rate=100,
					basic_amount=1000,
					additional_cost=500,
					landed_cost_voucher_amount=0,
					amount=1500,
					valuation_rate=150,
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
					transfer_qty=10,
					qty=10,
					basic_rate=100,
					basic_amount=1000,
					additional_cost=500,
					landed_cost_voucher_amount=0,
					amount=1000,
					valuation_rate=100,
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


if __name__ == "__main__":
	unittest.main()
