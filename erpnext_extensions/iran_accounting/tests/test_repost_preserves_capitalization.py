# Copyright (c) 2026, ERPNext Extensions contributors
"""Commit 5: repost must preserve Stock Entry capitalization."""

from __future__ import annotations

import unittest
from contextlib import contextmanager
from unittest import mock

from frappe.utils import flt

from erpnext_extensions.iran_accounting.domain.qty_rate_amount import align_stock_entry_item_amounts
from erpnext_extensions.iran_accounting.manufacture_rounding import (
	align_manufacture_finished_good_residual,
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
		"""Simulate post-repost align path used by _reconcile_stock_entry_after_repost."""
		outgoing = 3482885707
		add_cost = 2558380216
		expected = 6041265923
		qty = 3150.0
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
		self.assertEqual(flt(fg.amount), expected)
		self.assertEqual(flt(fg.additional_cost), add_cost)
		self.assertEqual(flt(doc.value_difference), add_cost)

	def test_reconcile_path_preserves_lcv(self):
		row = _Row(
			qty=10,
			transfer_qty=10,
			basic_rate=100,
			basic_amount=1000,
			additional_cost=0,
			landed_cost_voucher_amount=500,
			amount=1500,
			valuation_rate=150,
			s_warehouse=None,
			t_warehouse="Stores",
			is_finished_item=0,
		)
		doc = _Doc(doctype="Stock Entry", purpose="Material Receipt", company="Test", items=[row])
		with _irr():
			align_stock_entry_item_amounts(doc)
		self.assertEqual(flt(row.amount), 1500)
		self.assertEqual(flt(row.landed_cost_voucher_amount), 500)

	def test_idempotent_double_align(self):
		row = _Row(
			qty=10,
			transfer_qty=10,
			basic_rate=100,
			basic_amount=1000,
			additional_cost=250,
			landed_cost_voucher_amount=50,
			amount=1300,
			valuation_rate=130,
			s_warehouse=None,
			t_warehouse="Stores",
			is_finished_item=0,
		)
		doc = _Doc(doctype="Stock Entry", purpose="Material Receipt", company="Test", items=[row])
		with _irr():
			align_stock_entry_item_amounts(doc)
			a1 = flt(row.amount)
			align_stock_entry_item_amounts(doc)
			a2 = flt(row.amount)
		self.assertEqual(a1, 1300)
		self.assertEqual(a2, 1300)


if __name__ == "__main__":
	unittest.main()
