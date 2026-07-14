# Copyright (c) 2026, ERPNext Extensions contributors

from __future__ import annotations

import unittest
from contextlib import contextmanager
from unittest import mock

from frappe.utils import flt

from erpnext_extensions.iran_accounting.manufacture_rounding import (
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
		items.append(
			_SteRow(
				qty=2968.0,
				transfer_qty=2968.0,
				basic_rate=950455.748972372,
				valuation_rate=950455.748972372,
				basic_amount=2820952663.0,
				amount=2820952663.0,
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
			total_outgoing_value=2820952662.0,
			total_incoming_value=2820952663.0,
			value_difference=1.0,
		)

		with _irr_patches():
			align_manufacture_finished_good_to_outgoing(doc)

		fg = items[-1]
		self.assertEqual(doc.value_difference, 0)
		self.assertEqual(doc.total_outgoing_value, 2820952662)
		self.assertEqual(doc.total_incoming_value, 2820952662)
		self.assertEqual(fg.amount, 2820952662)
		self.assertEqual(fg.basic_amount, 2820952662)
		self.assertEqual(flt(fg.basic_rate), flt(2820952662 / 2968))
		self.assertEqual(fg.valuation_rate, fg.basic_rate)

	def test_align_skips_multi_finished_goods(self):
		doc = _SteDoc(
			doctype="Stock Entry",
			purpose="Manufacture",
			company="Test IRR Co",
			items=[
				_SteRow(
					amount=100,
					s_warehouse="W",
					qty=1,
					transfer_qty=1,
					is_finished_item=0,
				),
				_SteRow(
					amount=200,
					t_warehouse="W",
					qty=1,
					transfer_qty=1,
					is_finished_item=1,
				),
				_SteRow(
					amount=300,
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

	def test_validate_stock_entry_aligns_manufacture_totals(self):
		items = _staging_rm_rows()
		items.append(
			_SteRow(
				qty=2968.0,
				transfer_qty=2968.0,
				basic_rate=950455.748972372,
				valuation_rate=950455.748972372,
				basic_amount=2820952663.0,
				amount=2820952663.0,
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
			total_outgoing_value=2820952662.0,
			total_incoming_value=2820952663.0,
			value_difference=1.0,
		)

		with _irr_patches():
			validate_stock_entry(doc)

		self.assertEqual(doc.value_difference, 0)
		self.assertEqual(doc.total_incoming_value, doc.total_outgoing_value)


if __name__ == "__main__":
	unittest.main()
