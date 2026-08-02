# Copyright (c) 2026, ERPNext Extensions contributors

from __future__ import annotations

import unittest
from contextlib import contextmanager
from unittest import mock

from frappe.utils import flt

from erpnext_extensions.iran_accounting.manufacture_rounding import (
	align_manufacture_finished_good_residual,
	align_manufacture_finished_good_to_outgoing,
)
from erpnext_extensions.iran_accounting.stock_entry import validate_stock_entry


class _SteRow:
	"""Minimal Stock Entry Detail stand-in (Frappe v16 _dict has no .set)."""

	def __init__(self, **fields):
		self.__dict__.update(fields)

	def get(self, key, default=None):
		return self.__dict__.get(key, default)

	def set(self, key, value):
		self.__dict__[key] = value


class _SteDoc:
	def __init__(self, **fields):
		self.__dict__.update(fields)

	def get(self, key, default=None):
		return self.__dict__.get(key, default)


@contextmanager
def _irr_patches():
	with (
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
			"erpnext_extensions.iran_accounting.stock_entry.is_irr_company",
			return_value=True,
		),
		mock.patch(
			"erpnext_extensions.iran_accounting.domain.currency.is_irr_company",
			return_value=True,
		),
		mock.patch(
			"erpnext_extensions.iran_accounting.domain.currency.get_company_currency",
			return_value="IRR",
		),
		mock.patch(
			"erpnext_extensions.iran_accounting.domain.ledger_rounding.is_irr_company",
			return_value=True,
		),
		mock.patch(
			"erpnext_extensions.iran_accounting.domain.ledger_rounding.get_company_currency",
			return_value="IRR",
		),
		mock.patch(
			"erpnext_extensions.iran_accounting.rounding.is_irr_company",
			return_value=True,
		),
		mock.patch(
			"erpnext_extensions.iran_accounting.rounding.get_company_currency",
			return_value="IRR",
		),
		mock.patch(
			"erpnext_extensions.iran_accounting.domain.irr_rounding_residual.assert_round_off_ready_if_needed",
			return_value=None,
		),
	):
		yield


def _staging_rm_rows():
	"""Outgoing lines from MAT-STE-2026-03075 (integer amounts only)."""
	specs = [
		(30.0, 9161243.0, 274837290.0),
		(70.01, 17374247.0, 1216371032.0),
		(2.19632, 5195913.081918847, 11411888.0),
		(26.278188, 33624.003932691, 883578.0),
		(20.0007584, 18170.005496591, 363414.0),
		(11.5848, 12664.978765279, 146721.0),
		(38.616, 28931.0, 1117199.0),
		(3.7509584, 13892307.661136173, 52109468.0),
		(2968.0, 346357.0, 1027987576.0),
		(2968.0, 79422.0, 235724496.0),
	]
	rows = []
	for qty, rate, amount in specs:
		rows.append(
			_SteRow(
				qty=qty,
				transfer_qty=qty,
				basic_rate=rate,
				valuation_rate=rate,
				basic_amount=amount,
				additional_cost=0,
				landed_cost_voucher_amount=0,
				amount=amount,
				s_warehouse="RM Stores",
				t_warehouse=None,
				is_finished_item=0,
			)
		)
	return rows


class TestManufactureRounding(unittest.TestCase):
	def test_align_fixes_staging_one_rial_discrepancy(self):
		items = _staging_rm_rows()
		outgoing = sum(r.amount for r in items)
		items.append(
			_SteRow(
				qty=2968.0,
				transfer_qty=2968.0,
				basic_rate=outgoing / 2968.0,
				valuation_rate=(outgoing + 1) / 2968.0,
				basic_amount=outgoing + 1,
				additional_cost=0,
				landed_cost_voucher_amount=0,
				amount=outgoing + 1,
				s_warehouse=None,
				t_warehouse="FG Stores",
				is_finished_item=1,
			)
		)
		doc = _SteDoc(
			doctype="Stock Entry",
			purpose="Manufacture",
			company="Test IRR Co",
			items=items,
			total_outgoing_value=outgoing,
			total_incoming_value=outgoing + 1,
			value_difference=1.0,
		)

		with _irr_patches():
			align_manufacture_finished_good_residual(doc)

		fg = items[-1]
		self.assertEqual(doc.value_difference, 0)
		self.assertEqual(doc.total_outgoing_value, outgoing)
		self.assertEqual(doc.total_incoming_value, outgoing)
		self.assertEqual(fg.amount, outgoing)
		self.assertEqual(fg.basic_amount, outgoing)

	def test_align_skips_multi_finished_goods(self):
		doc = _SteDoc(
			doctype="Stock Entry",
			purpose="Manufacture",
			company="Test IRR Co",
			items=[
				_SteRow(
					amount=100,
					basic_amount=100,
					additional_cost=0,
					landed_cost_voucher_amount=0,
					s_warehouse="W",
					qty=1,
					transfer_qty=1,
					is_finished_item=0,
				),
				_SteRow(
					amount=200,
					basic_amount=200,
					additional_cost=0,
					landed_cost_voucher_amount=0,
					t_warehouse="W",
					qty=1,
					transfer_qty=1,
					is_finished_item=1,
				),
				_SteRow(
					amount=300,
					basic_amount=300,
					additional_cost=0,
					landed_cost_voucher_amount=0,
					t_warehouse="W",
					qty=1,
					transfer_qty=1,
					is_finished_item=1,
				),
			],
			total_incoming_value=500,
			total_outgoing_value=100,
			value_difference=400,
		)
		with _irr_patches():
			align_manufacture_finished_good_to_outgoing(doc)
		self.assertEqual(doc.value_difference, 400)

	def test_manufacture_with_additional_cost_preserved(self):
		outgoing = 3482885707
		add_cost = 2558380216
		expected = 6041265923
		qty = 3150.0
		items = [
			_SteRow(
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
			),
			_SteRow(
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
			),
		]
		doc = _SteDoc(
			doctype="Stock Entry",
			purpose="Manufacture",
			company="Test IRR Co",
			items=items,
			total_outgoing_value=outgoing,
			total_incoming_value=expected,
			value_difference=add_cost,
		)
		with _irr_patches():
			align_manufacture_finished_good_residual(doc)
		fg = items[-1]
		self.assertEqual(flt(fg.amount), expected)
		self.assertEqual(flt(fg.additional_cost), add_cost)
		self.assertEqual(flt(doc.value_difference), add_cost)
		# Integer valuation_rate from amount; may differ from rounded basic_rate
		self.assertEqual(flt(fg.valuation_rate), round(expected / qty))
		self.assertNotEqual(flt(fg.valuation_rate), flt(fg.basic_rate))

	def test_repack_with_additional_cost_rate_first(self):
		# Rate-first: basic_rate 176, basic 1232, +137 → amount 1369 (not 1371)
		items = [
			_SteRow(
				qty=7,
				transfer_qty=7,
				basic_rate=1234 / 7,
				basic_amount=1234,
				additional_cost=0,
				landed_cost_voucher_amount=0,
				amount=1234,
				valuation_rate=1234 / 7,
				s_warehouse="RM",
				t_warehouse=None,
				is_finished_item=0,
			),
			_SteRow(
				qty=7,
				transfer_qty=7,
				basic_rate=1234 / 7,
				basic_amount=1234,
				additional_cost=137,
				landed_cost_voucher_amount=0,
				amount=1371,
				valuation_rate=1371 / 7,
				s_warehouse=None,
				t_warehouse="FG",
				is_finished_item=1,
			),
		]
		doc = _SteDoc(
			doctype="Stock Entry",
			purpose="Repack",
			company="Test IRR Co",
			items=items,
			total_outgoing_value=1234,
			total_incoming_value=1371,
			value_difference=137,
		)
		with _irr_patches():
			validate_stock_entry(doc)
		fg = items[-1]
		self.assertEqual(flt(fg.basic_rate), 176)
		self.assertEqual(flt(fg.basic_amount), 1232)
		self.assertEqual(flt(fg.amount), 1369)
		self.assertEqual(flt(fg.valuation_rate), 196)  # round(1369/7)
		self.assertEqual(flt(doc.value_difference), 137)

	def test_manufacture_amount_1371_residual_minus_one(self):
		"""Preferred residual: amount 1371 stays; valuation_rate 196; residual -1."""
		items = [
			_SteRow(
				qty=7,
				transfer_qty=7,
				basic_rate=176,
				basic_amount=1232,
				additional_cost=0,
				landed_cost_voucher_amount=0,
				amount=1232,
				valuation_rate=176,
				s_warehouse="RM",
				t_warehouse=None,
				is_finished_item=0,
			),
			_SteRow(
				qty=7,
				transfer_qty=7,
				basic_rate=176,
				basic_amount=1232,
				additional_cost=139,
				landed_cost_voucher_amount=0,
				amount=1371,
				valuation_rate=1371 / 7,
				s_warehouse=None,
				t_warehouse="FG",
				is_finished_item=1,
			),
		]
		doc = _SteDoc(
			doctype="Stock Entry",
			purpose="Manufacture",
			company="Test IRR Co",
			items=items,
			total_outgoing_value=1232,
			total_incoming_value=1371,
			value_difference=139,
		)
		with _irr_patches():
			align_manufacture_finished_good_residual(doc)
		fg = items[-1]
		self.assertEqual(flt(fg.amount), 1371)
		self.assertEqual(flt(fg.valuation_rate), 196)
		self.assertEqual(1371 - 196 * 7, -1)

	def test_manufacture_without_additional_cost_residual_only(self):
		items = _staging_rm_rows()
		outgoing = sum(r.amount for r in items)
		items.append(
			_SteRow(
				qty=2968.0,
				transfer_qty=2968.0,
				basic_rate=outgoing / 2968.0,
				valuation_rate=outgoing / 2968.0,
				basic_amount=outgoing,
				additional_cost=0,
				landed_cost_voucher_amount=0,
				amount=outgoing,
				s_warehouse=None,
				t_warehouse="FG Stores",
				is_finished_item=1,
			)
		)
		doc = _SteDoc(
			doctype="Stock Entry",
			purpose="Manufacture",
			company="Test IRR Co",
			items=items,
			total_outgoing_value=outgoing,
			total_incoming_value=outgoing,
			value_difference=0,
		)
		with _irr_patches():
			# Residual path only — avoid re-deriving RM rates (fixture uses stored amounts)
			align_manufacture_finished_good_residual(doc)
		self.assertEqual(doc.value_difference, 0)
		self.assertEqual(doc.total_incoming_value, doc.total_outgoing_value)
		fg = items[-1]
		self.assertEqual(flt(fg.valuation_rate), round(outgoing / 2968.0))

	def test_large_value_difference_not_treated_as_residual(self):
		# Δ=5 IRR is beyond ±1 residual tolerance — must not force-equal
		doc = _SteDoc(
			doctype="Stock Entry",
			purpose="Manufacture",
			company="Test IRR Co",
			items=[
				_SteRow(
					amount=1234,
					basic_amount=1234,
					additional_cost=0,
					landed_cost_voucher_amount=0,
					s_warehouse="W",
					qty=7,
					transfer_qty=7,
					is_finished_item=0,
					basic_rate=1234 / 7,
					valuation_rate=1234 / 7,
				),
				_SteRow(
					amount=1239,
					basic_amount=1239,
					additional_cost=0,
					landed_cost_voucher_amount=0,
					t_warehouse="W",
					qty=7,
					transfer_qty=7,
					is_finished_item=1,
					basic_rate=1239 / 7,
					valuation_rate=1239 / 7,
				),
			],
			total_incoming_value=1239,
			total_outgoing_value=1234,
			value_difference=5,
		)
		with _irr_patches():
			align_manufacture_finished_good_residual(doc)
		self.assertEqual(doc.value_difference, 5)
		self.assertEqual(doc.items[-1].amount, 1239)


if __name__ == "__main__":
	unittest.main()
