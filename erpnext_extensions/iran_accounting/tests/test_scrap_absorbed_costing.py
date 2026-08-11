# Copyright (c) 2026, ERPNext Extensions contributors
"""Absorbed-cost scrap valuation.

Figures mirror the staging chain that exposed the defect
(MFG-WO-2026-00360 / PO-JOB03991 / MAT-STE-2026-03964).
"""

from __future__ import annotations

import unittest
from contextlib import contextmanager
from unittest import mock

from frappe.utils import flt

from erpnext_extensions.iran_accounting.scrap_costing import (
	allocate_scrap_absorbed_cost,
	is_scrap_row,
	permit_scrap_zero_valuation,
)

MODULE = "erpnext_extensions.iran_accounting.scrap_costing"


class _Row:
	"""Minimal Stock Entry Detail stand-in."""

	def __init__(self, **fields):
		self.__dict__.setdefault("allow_zero_valuation_rate", 0)
		self.__dict__.update(fields)

	def get(self, key, default=None):
		return self.__dict__.get(key, default)

	def set(self, key, value):
		self.__dict__[key] = value


class _Doc:
	def __init__(self, **fields):
		self.__dict__.setdefault("doctype", "Stock Entry")
		self.__dict__.setdefault("purpose", "Manufacture")
		self.__dict__.setdefault("company", "اسپاد فارمد دارو")
		self.__dict__.update(fields)

	def get(self, key, default=None):
		return self.__dict__.get(key, default)


def _consumed(item_code, qty, rate):
	return _Row(
		item_code=item_code,
		qty=qty,
		transfer_qty=qty,
		basic_rate=rate,
		basic_amount=qty * rate,
		amount=qty * rate,
		s_warehouse="WIP",
		t_warehouse=None,
		is_finished_item=0,
	)


def _output(item_code, qty, is_fg=0, row_type=None, rate=0.0):
	return _Row(
		item_code=item_code,
		qty=qty,
		transfer_qty=qty,
		basic_rate=rate,
		basic_amount=qty * rate,
		amount=qty * rate,
		s_warehouse=None,
		t_warehouse="Quarantine",
		is_finished_item=is_fg,
		type=row_type,
	)


@contextmanager
def _irr(main_item_codes=None):
	"""IRR company, precision 0, and the Z-code scrap convention."""
	lookup = main_item_codes or {}

	def _get_value(doctype, name, field):
		if doctype == "Item" and field == "custom_main_item_code":
			return lookup.get(name)
		return None

	with (
		mock.patch(f"{MODULE}.is_irr_company", return_value=True),
		mock.patch(f"{MODULE}.get_company_currency", return_value="IRR"),
		mock.patch(f"{MODULE}.get_currency_precision", return_value=0),
		mock.patch(f"{MODULE}.frappe.db.get_value", side_effect=_get_value),
	):
		yield


class TestScrapAbsorbedCosting(unittest.TestCase):
	# ---------------------------------------------------------------- staging case
	def _staging_doc(self):
		"""The real MAT-STE-2026-03964 shape: alternative + two batches + two scraps."""
		return _Doc(
			items=[
				_consumed("13100024", 800, 79422),
				_consumed("13100023", 200, 346357),  # batch 1248
				_consumed("13100001", 250, 337526),  # alternative material
				_output("30100291", 600, is_fg=1),
				_output("Z13100023", 25, row_type="Scrap"),
				_output("Z13100024", 10, row_type="Scrap"),
				_consumed("13100023", 200, 346357),  # batch 1250
			]
		)

	def test_reconciles_exactly_with_zero_residual(self):
		doc = self._staging_doc()
		with _irr():
			self.assertTrue(allocate_scrap_absorbed_cost(doc))

		pool = sum(flt(r.amount) for r in doc.items if r.get("s_warehouse"))
		out = sum(flt(r.amount) for r in doc.items if r.get("t_warehouse"))
		self.assertEqual(pool, 286461900)
		self.assertEqual(out, pool, "output must consume the pool with no residual")

	def test_matches_the_rates_observed_on_staging(self):
		doc = self._staging_doc()
		with _irr():
			allocate_scrap_absorbed_cost(doc)

		fg = next(r for r in doc.items if r.get("is_finished_item"))
		scrap = [r for r in doc.items if r.get("type") == "Scrap"]
		self.assertEqual(fg.basic_rate, 451120)
		self.assertEqual(fg.amount, 270672000)
		self.assertEqual({r.basic_rate for r in scrap}, {451140})
		self.assertEqual(sum(flt(r.amount) for r in scrap), 15789900)

	def test_rates_are_whole_units(self):
		doc = self._staging_doc()
		with _irr():
			allocate_scrap_absorbed_cost(doc)
		for row in doc.items:
			if row.get("t_warehouse"):
				self.assertEqual(flt(row.basic_rate), int(flt(row.basic_rate)))

	# ---------------------------------------------------------------- valuation gap
	def test_scrap_without_previous_valuation_is_permitted_through_validate(self):
		"""The five-stage failure: scrap unknown in the target warehouse."""
		doc = _Doc(items=[_consumed("13100023", 100, 346357), _output("Z13100023", 3, row_type="Scrap")])
		with _irr():
			permit_scrap_zero_valuation(doc)
		scrap = doc.items[1]
		self.assertEqual(scrap.allow_zero_valuation_rate, 1)

	def test_permission_flag_is_withdrawn_once_a_real_rate_exists(self):
		doc = self._staging_doc()
		with _irr():
			permit_scrap_zero_valuation(doc)
			allocate_scrap_absorbed_cost(doc)
		for row in doc.items:
			if row.get("type") == "Scrap":
				self.assertEqual(row.allow_zero_valuation_rate, 0)
				self.assertGreater(flt(row.basic_rate), 0)

	def test_scrap_with_existing_valuation_is_still_recosted(self):
		"""A stale rate from another warehouse must not survive."""
		doc = _Doc(
			items=[
				_consumed("13100023", 100, 346357),
				_output("30100033", 95, is_fg=1),
				_output("Z13100023", 3, row_type="Scrap", rate=999999),
			]
		)
		with _irr():
			allocate_scrap_absorbed_cost(doc)
		scrap = doc.items[2]
		self.assertNotEqual(scrap.basic_rate, 999999)
		total = sum(flt(r.amount) for r in doc.items if r.get("t_warehouse"))
		self.assertEqual(total, 34635700)

	# ---------------------------------------------------------------- conventions
	def test_scrap_detected_by_z_code_convention_without_explicit_type(self):
		row = _output("Z13100023", 3)
		with _irr(main_item_codes={"Z13100023": "13100023"}):
			self.assertTrue(is_scrap_row(row))

	def test_finished_good_is_never_treated_as_scrap(self):
		row = _output("30100291", 600, is_fg=1)
		with _irr(main_item_codes={"30100291": "whatever"}):
			self.assertFalse(is_scrap_row(row))

	def test_consumed_row_is_never_treated_as_scrap(self):
		row = _consumed("Z13100023", 5, 1000)
		with _irr(main_item_codes={"Z13100023": "13100023"}):
			self.assertFalse(is_scrap_row(row))

	# ---------------------------------------------------------------- boundaries
	def test_no_scrap_leaves_the_document_untouched(self):
		doc = _Doc(items=[_consumed("13100023", 100, 346357), _output("30100033", 95, is_fg=1)])
		with _irr():
			self.assertFalse(allocate_scrap_absorbed_cost(doc))
		self.assertEqual(doc.items[1].basic_rate, 0)

	def test_multi_finished_good_is_left_to_erpnext(self):
		doc = _Doc(
			items=[
				_consumed("13100023", 100, 346357),
				_output("30100033", 50, is_fg=1),
				_output("30100036", 45, is_fg=1),
				_output("Z13100023", 3, row_type="Scrap"),
			]
		)
		with _irr():
			self.assertFalse(allocate_scrap_absorbed_cost(doc))

	def test_by_product_keeps_its_own_allocation_and_leaves_the_pool(self):
		doc = _Doc(
			items=[
				_consumed("13100023", 100, 346357),
				_output("30100033", 90, is_fg=1),
				_output("BY-1", 5, row_type="By-Product", rate=100000),
				_output("Z13100023", 3, row_type="Scrap"),
			]
		)
		with _irr():
			allocate_scrap_absorbed_cost(doc)
		by_product = doc.items[2]
		self.assertEqual(by_product.amount, 500000, "by-product allocation must be preserved")
		pool = 34635700 - 500000
		fg, scrap = doc.items[1], doc.items[3]
		# 90 good and 3 scrap cannot consume this pool exactly; the leftover is
		# bounded by gcd(90, 3) / 2 and shows up as an ordinary rounding residual
		self.assertLessEqual(abs(flt(fg.amount) + flt(scrap.amount) - pool), 2)

	def test_both_rows_stay_exact_when_no_exact_split_exists(self):
		"""Stage 2 of the five-stage product: 92 good, 2 scrap, odd pool.

		92 x rate is always even, so an odd pool can never be consumed exactly.
		The ledger contract checks rate x qty against each row's amount, so a
		remainder may never be parked in one row — both must stay exact.
		"""
		doc = _Doc(
			items=[
				_consumed("30100033", 95, 1986819),  # odd pool
				_output("30100036", 92, is_fg=1),
				_output("Z30100033", 2, row_type="Scrap"),
			]
		)
		pool = 95 * 1986819
		self.assertEqual(pool % 2, 1, "fixture must produce an odd pool")
		with _irr():
			self.assertTrue(allocate_scrap_absorbed_cost(doc))

		fg, scrap = doc.items[1], doc.items[2]
		for row, qty in ((fg, 92), (scrap, 2)):
			self.assertEqual(
				flt(row.basic_amount),
				flt(row.basic_rate) * qty,
				"rate x qty must reconcile exactly on every row",
			)
			self.assertEqual(flt(row.basic_rate), int(flt(row.basic_rate)))
		self.assertLessEqual(abs(flt(fg.basic_amount) + flt(scrap.basic_amount) - pool), 1)

	def test_non_manufacture_purpose_is_ignored(self):
		doc = self._staging_doc()
		doc.purpose = "Material Transfer for Manufacture"
		with _irr():
			self.assertFalse(allocate_scrap_absorbed_cost(doc))

	def test_non_irr_company_is_ignored(self):
		doc = self._staging_doc()
		with mock.patch(f"{MODULE}.is_irr_company", return_value=False):
			self.assertFalse(allocate_scrap_absorbed_cost(doc))

	# ---------------------------------------------------------------- multi-stage
	def test_multi_stage_semi_finished_chain_each_stage_reconciles(self):
		"""Stage N consumes stage N-1's semi-FG; every stage must balance."""
		stages = [
			("30100033", 95, [("13100023", 100, 346357), ("13100024", 100, 79422)], 3),
			("30100036", 92, [("30100033", 95, 447000)], 2),
			("30200022", 88, [("30100036", 92, 462000)], 4),
		]
		for fg_item, fg_qty, consumed, scrap_qty in stages:
			doc = _Doc(
				items=[_consumed(code, qty, rate) for code, qty, rate in consumed]
				+ [
					_output(fg_item, fg_qty, is_fg=1),
					_output("Z" + fg_item, scrap_qty, row_type="Scrap"),
				]
			)
			with _irr():
				applied = allocate_scrap_absorbed_cost(doc)
			pool = sum(flt(r.amount) for r in doc.items if r.get("s_warehouse"))
			out = sum(flt(r.amount) for r in doc.items if r.get("t_warehouse"))
			self.assertTrue(applied, f"stage {fg_item} was not costed")
			self.assertEqual(out, pool, f"stage {fg_item} left a residual")

	# ---------------------------------------------------------------- process loss
	def test_process_loss_units_receive_no_share_and_are_absorbed(self):
		"""1000 started, 600 good, 35 scrap: the 365 lost units take no cost."""
		doc = _Doc(
			items=[
				_consumed("13100023", 1000, 100000),
				_output("30100291", 600, is_fg=1),
				_output("Z13100023", 35, row_type="Scrap"),
			]
		)
		with _irr():
			allocate_scrap_absorbed_cost(doc)
		fg, scrap = doc.items[1], doc.items[2]
		self.assertEqual(flt(fg.amount) + flt(scrap.amount), 100000000)
		# absorbed rate is far above the input rate precisely because the lost
		# units contributed cost but no output
		self.assertGreater(flt(fg.basic_rate), 100000)

	# ------------------------------------------------------- capitalised cost
	def test_capitalised_operating_cost_is_never_wiped(self):
		"""Real products capitalise Work Order operating cost onto the FG row.

		Reproduces the five-stage staging failure: materials 90,573,834 with
		91,370,722 of operating cost. Overwriting ``amount`` with rate x qty
		discarded the operating cost and tripped the ledger contract.
		"""
		fg = _output("30100033", 95, is_fg=1)
		fg.additional_cost = 91370722
		doc = _Doc(
			items=[
				_consumed("13100023", 100, 346357),
				_consumed("13100024", 100, 79422),
				_consumed("18000007", 2.8, 13800000),
				fg,
				_output("Z13100023", 3, row_type="Scrap"),
			]
		)
		with _irr():
			self.assertTrue(allocate_scrap_absorbed_cost(doc))

		materials = sum(flt(r.basic_amount) for r in doc.items if r.get("s_warehouse"))
		scrap = doc.items[4]
		# material pool is split between the two output rows
		self.assertEqual(flt(fg.basic_amount) + flt(scrap.basic_amount), materials)
		# capitalisation survives and rides on amount, not basic_amount
		self.assertEqual(flt(fg.amount), flt(fg.basic_amount) + 91370722)
		# the identity the ledger contract enforces
		incoming = sum(flt(r.amount) for r in doc.items if r.get("t_warehouse"))
		self.assertEqual(incoming, materials + 91370722)

	def test_scrap_carries_no_capitalised_cost(self):
		fg = _output("30100033", 95, is_fg=1)
		fg.additional_cost = 1000000
		doc = _Doc(
			items=[
				_consumed("13100023", 100, 346357),
				fg,
				_output("Z13100023", 3, row_type="Scrap"),
			]
		)
		with _irr():
			allocate_scrap_absorbed_cost(doc)
		scrap = doc.items[2]
		self.assertEqual(flt(scrap.amount), flt(scrap.basic_amount))

	def test_scrap_sharing_the_finished_good_item_code(self):
		"""Rejected units now keep the product's own item code and GMP batch.

		Reproduces MAT-STE-2026-03989 exactly: 690 good and 3 rejected units of
		30200023 against a 1,466,815,501 pool. 693 does not divide it — the pool
		is 1 mod 3 while 690a + 3b is always 0 mod 3 — so no integer pair
		consumes it exactly and the leftover must land in the residual rather
		than in either row's amount.
		"""
		fg = _output("30200023", 690, is_fg=1)
		fg.additional_cost = 91370722
		scrap = _output("30200023", 3, row_type="Scrap")
		doc = _Doc(items=[_consumed("17000005", 1, 1466815501), fg, scrap])

		with _irr():
			self.assertTrue(allocate_scrap_absorbed_cost(doc))

		# A reject cost the same as a good unit. The two rates are not bit
		# identical because both must stay whole-rial and exact: the scrap rate
		# absorbs the sub-unit remainder, here 27 rial on 2.1m, or 0.0013%.
		self.assertLess(
			abs(flt(fg.basic_rate) - flt(scrap.basic_rate)) / flt(fg.basic_rate),
			1e-4,
		)
		# the identity the ledger contract checks, on BOTH rows
		self.assertEqual(flt(fg.basic_rate) * 690, flt(fg.basic_amount))
		self.assertEqual(flt(scrap.basic_rate) * 3, flt(scrap.basic_amount))
		# capitalised operating cost is preserved, not redistributed
		self.assertEqual(flt(fg.amount), flt(fg.basic_amount) + 91370722)
		self.assertEqual(flt(scrap.amount), flt(scrap.basic_amount))
		# and the unconsumed remainder stays negligible
		leftover = 1466815501 - flt(fg.basic_amount) - flt(scrap.basic_amount)
		self.assertLessEqual(abs(leftover), 3)

	def test_quantities_and_identity_are_never_modified(self):
		doc = self._staging_doc()
		before = [(r.item_code, flt(r.qty), flt(r.transfer_qty)) for r in doc.items]
		with _irr():
			allocate_scrap_absorbed_cost(doc)
		after = [(r.item_code, flt(r.qty), flt(r.transfer_qty)) for r in doc.items]
		self.assertEqual(before, after)


if __name__ == "__main__":
	unittest.main()
