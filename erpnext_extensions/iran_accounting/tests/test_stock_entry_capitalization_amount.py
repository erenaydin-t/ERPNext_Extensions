# Copyright (c) 2026, ERPNext Extensions contributors
"""Commit 1: Stock Entry amount ownership preserves ERPNext capitalization."""

from __future__ import annotations

import unittest
from contextlib import contextmanager
from unittest import mock

from frappe.utils import flt

from erpnext_extensions.iran_accounting.domain.qty_rate_amount import (
	align_stock_entry_item_amounts,
	compose_stock_entry_row_amount,
)
from erpnext_extensions.iran_accounting.domain.stock_entry_sync import stock_entry_row_amount


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
		row = _Row(basic_amount=1000, additional_cost=250, landed_cost_voucher_amount=50)
		self.assertEqual(compose_stock_entry_row_amount(row, "IRR"), 1300)

	def test_align_preserves_additional_cost(self):
		row = _Row(
			qty=10,
			transfer_qty=10,
			basic_rate=100,
			basic_amount=1000,
			additional_cost=500,
			landed_cost_voucher_amount=0,
			amount=1500,
			valuation_rate=150,
		)
		doc = _Doc(doctype="Stock Entry", company="Test IRR Co", items=[row])
		with _irr_currency_patches():
			align_stock_entry_item_amounts(doc)
		self.assertEqual(flt(row.basic_amount), 1000)
		self.assertEqual(flt(row.additional_cost), 500)
		self.assertEqual(flt(row.amount), 1500)
		self.assertEqual(flt(row.valuation_rate), 150)

	def test_align_preserves_landed_cost(self):
		row = _Row(
			qty=10,
			transfer_qty=10,
			basic_rate=100,
			basic_amount=1000,
			additional_cost=0,
			landed_cost_voucher_amount=500,
			amount=1500,
			valuation_rate=150,
		)
		doc = _Doc(doctype="Stock Entry", company="Test IRR Co", items=[row])
		with _irr_currency_patches():
			align_stock_entry_item_amounts(doc)
		self.assertEqual(flt(row.amount), 1500)
		self.assertEqual(flt(row.landed_cost_voucher_amount), 500)
		self.assertEqual(flt(row.valuation_rate), 150)

	def test_align_uses_transfer_qty_not_qty(self):
		# stock_uom qty=2, conversion 5 → transfer_qty=10
		row = _Row(
			qty=2,
			transfer_qty=10,
			basic_rate=100,
			basic_amount=200,  # wrong stale value using qty
			additional_cost=0,
			landed_cost_voucher_amount=0,
			amount=200,
			valuation_rate=100,
		)
		doc = _Doc(doctype="Stock Entry", company="Test IRR Co", items=[row])
		with _irr_currency_patches():
			align_stock_entry_item_amounts(doc)
		self.assertEqual(flt(row.basic_amount), 1000)
		self.assertEqual(flt(row.amount), 1000)
		self.assertEqual(flt(row.valuation_rate), 100)

	def test_align_zero_transfer_qty_safe(self):
		row = _Row(
			qty=0,
			transfer_qty=0,
			basic_rate=100,
			basic_amount=0,
			additional_cost=0,
			landed_cost_voucher_amount=0,
			amount=0,
			valuation_rate=0,
		)
		doc = _Doc(doctype="Stock Entry", company="Test IRR Co", items=[row])
		with _irr_currency_patches():
			align_stock_entry_item_amounts(doc)
		self.assertEqual(flt(row.amount), 0)

	def test_stock_entry_row_amount_fallback_composes_capitalization(self):
		row = _Row(
			amount=None,
			transfer_qty=10,
			basic_rate=100,
			basic_amount=1000,
			additional_cost=400,
			landed_cost_voucher_amount=100,
		)
		with _irr_currency_patches():
			self.assertEqual(stock_entry_row_amount(row, "Test IRR Co"), 1500)

	def test_reported_manufacture_figures_preserved(self):
		outgoing = 3482885707
		add_cost = 2558380216
		expected = 6041265923
		qty = 3150.0
		row = _Row(
			qty=qty,
			transfer_qty=qty,
			basic_rate=outgoing / qty,
			basic_amount=outgoing,
			additional_cost=add_cost,
			landed_cost_voucher_amount=0,
			amount=expected,
			valuation_rate=expected / qty,
		)
		doc = _Doc(doctype="Stock Entry", purpose="Manufacture", company="Test IRR Co", items=[row])
		with _irr_currency_patches():
			align_stock_entry_item_amounts(doc)
		self.assertEqual(flt(row.amount), expected)
		self.assertEqual(flt(row.additional_cost), add_cost)
		self.assertAlmostEqual(flt(row.valuation_rate), expected / qty)


if __name__ == "__main__":
	unittest.main()
