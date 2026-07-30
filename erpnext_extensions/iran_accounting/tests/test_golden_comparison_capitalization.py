# Copyright (c) 2026, ERPNext Extensions contributors
"""Golden comparison: iran_accounting vs ERPNext ownership for Stock Entry economics.

Documents that after 3.7.6, iran_accounting must match ERPNext capitalization
economics; differences are limited to documented IRR residual rounding or the
approved zero-value transfer GL shape.
"""

from __future__ import annotations

import unittest
from contextlib import contextmanager
from unittest import mock

from frappe.utils import flt

from erpnext_extensions.iran_accounting.domain.qty_rate_amount import align_stock_entry_item_amounts
from erpnext_extensions.iran_accounting.manufacture_rounding import (
	align_manufacture_finished_good_residual,
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
	"""ERPNext update_valuation_rate amount identity."""
	return flt(basic_amount) + flt(additional_cost) + flt(landed_cost)


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
		basic = 3482885707
		add = 2558380216
		qty = 3150.0
		erpnext_amount = _erpnext_compose(basic, add, 0)
		erpnext_rate = erpnext_amount / qty

		fg = _Row(
			qty=qty,
			transfer_qty=qty,
			basic_rate=basic / qty,
			basic_amount=basic,
			additional_cost=add,
			landed_cost_voucher_amount=0,
			amount=erpnext_amount,
			valuation_rate=erpnext_rate,
			s_warehouse=None,
			t_warehouse="FG",
			is_finished_item=1,
		)
		rm = _Row(
			qty=1,
			transfer_qty=1,
			basic_rate=basic,
			basic_amount=basic,
			additional_cost=0,
			landed_cost_voucher_amount=0,
			amount=basic,
			valuation_rate=basic,
			s_warehouse="RM",
			t_warehouse=None,
			is_finished_item=0,
		)
		doc = _Doc(
			doctype="Stock Entry",
			purpose="Manufacture",
			company="Test",
			items=[rm, fg],
			total_outgoing_value=basic,
			total_incoming_value=erpnext_amount,
			value_difference=add,
		)
		with _irr():
			align_stock_entry_item_amounts(doc)
			align_manufacture_finished_good_residual(doc)

		self.assertEqual(flt(fg.amount), erpnext_amount)
		self.assertAlmostEqual(flt(fg.valuation_rate), erpnext_rate)
		self.assertEqual(flt(doc.value_difference), add)

	def test_lcv_matches_erpnext_economics(self):
		basic = 1000000
		lcv = 500000
		qty = 10
		erpnext_amount = _erpnext_compose(basic, 0, lcv)
		row = _Row(
			qty=qty,
			transfer_qty=qty,
			basic_rate=100000,
			basic_amount=basic,
			additional_cost=0,
			landed_cost_voucher_amount=lcv,
			amount=erpnext_amount,
			valuation_rate=erpnext_amount / qty,
			s_warehouse=None,
			t_warehouse="S",
			is_finished_item=0,
		)
		doc = _Doc(doctype="Stock Entry", purpose="Material Receipt", company="Test", items=[row])
		with _irr():
			align_stock_entry_item_amounts(doc)
		self.assertEqual(flt(row.amount), erpnext_amount)
		self.assertEqual(flt(row.landed_cost_voucher_amount), lcv)

	def test_zero_value_transfer_uses_iran_shape_not_core_builder(self):
		self.assertIn("Material Transfer", ZERO_VALUE_TRANSFER_STOCK_ENTRY_PURPOSES)

		class Doc:
			doctype = "Stock Entry"
			purpose = "Material Transfer"
			company = "Test"
			total_incoming_value = 1000
			total_outgoing_value = 1000
			value_difference = 0

			def set_total_incoming_outgoing_value(self):
				pass

		self.assertTrue(_should_force_balanced_transfer_gl(Doc(), 0))

	def test_conversion_factor_uses_transfer_qty(self):
		# qty in alternate UOM=2, transfer_qty in stock UOM=10
		row = _Row(
			qty=2,
			transfer_qty=10,
			basic_rate=100,
			basic_amount=200,
			additional_cost=0,
			landed_cost_voucher_amount=0,
			amount=200,
			valuation_rate=100,
			s_warehouse=None,
			t_warehouse="S",
			is_finished_item=0,
		)
		doc = _Doc(doctype="Stock Entry", purpose="Material Receipt", company="Test", items=[row])
		with _irr():
			align_stock_entry_item_amounts(doc)
		self.assertEqual(flt(row.basic_amount), 1000)
		self.assertEqual(flt(row.amount), 1000)
		self.assertEqual(flt(row.valuation_rate), 100)


if __name__ == "__main__":
	unittest.main()
