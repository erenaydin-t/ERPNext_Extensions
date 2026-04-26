from __future__ import annotations

import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import patch

from frappe.exceptions import ValidationError

from erpnext_extensions.cheque_management.pdc_open_advance import (
	get_open_advance_for_order,
	get_pdc_open_advance_by_order,
	get_pdc_open_advance_instrument,
	is_pdc_advance_allocatable,
)


def _fake_frappe(*, db) -> SimpleNamespace:
	def _throw(msg, *args, **kwargs):
		raise ValidationError(msg)

	return SimpleNamespace(db=db, throw=_throw, log_error=lambda *a, **k: None, logger=lambda *a, **k: None)


class TestPDCAOpenAdvance(unittest.TestCase):
	def test_recognition_not_posted_open_zero(self) -> None:
		with ExitStack() as stack:
			db = SimpleNamespace(
				get_value=lambda *a, **k: {
						"name": "PDC-A1",
						"allocation_mode": "advance",
						"cheque_amount": 1000.0,
						"recognition_je_posted": 0,
						"instrument_dead": 0,
						"instrument_dead_reason": None,
					},
				sql=lambda *a, **k: [],
				table_exists=lambda *a, **k: False,
			)
			stack.enter_context(patch("erpnext_extensions.cheque_management.pdc_open_advance.frappe", _fake_frappe(db=db)))
			stack.enter_context(patch("erpnext_extensions.cheque_management.pdc_open_advance._", lambda s: s))
			out = get_pdc_open_advance_instrument("PDC-A1")
			self.assertEqual(out["recognized_gross"], 0.0)
			self.assertEqual(out["open_amount"], 0.0)
			self.assertFalse(out["allocatable"])

	def test_recognition_posted_no_applications_open_full(self) -> None:
		with ExitStack() as stack:
			db = SimpleNamespace(
				get_value=lambda *a, **k: {
						"name": "PDC-A2",
						"allocation_mode": "advance",
						"cheque_amount": 20000.0,
						"recognition_je_posted": 1,
						"instrument_dead": 0,
						"instrument_dead_reason": None,
					},
				sql=lambda *a, **k: [],
				table_exists=lambda *a, **k: False,
			)
			stack.enter_context(patch("erpnext_extensions.cheque_management.pdc_open_advance.frappe", _fake_frappe(db=db)))
			stack.enter_context(patch("erpnext_extensions.cheque_management.pdc_open_advance._", lambda s: s))
			out = get_pdc_open_advance_instrument("PDC-A2")
			self.assertEqual(out["recognized_gross"], 20000.0)
			self.assertEqual(out["applied_amount"], 0.0)
			self.assertEqual(out["reversed_amount"], 0.0)
			self.assertEqual(out["open_amount"], 20000.0)
			self.assertTrue(out["allocatable"])

	def test_dead_instrument_open_zero(self) -> None:
		with ExitStack() as stack:
			db = SimpleNamespace(
				get_value=lambda *a, **k: {
						"name": "PDC-A3",
						"allocation_mode": "advance",
						"cheque_amount": 1000.0,
						"recognition_je_posted": 1,
						"instrument_dead": 1,
						"instrument_dead_reason": "reversed",
					},
				sql=lambda *a, **k: [],
				table_exists=lambda *a, **k: False,
			)
			stack.enter_context(patch("erpnext_extensions.cheque_management.pdc_open_advance.frappe", _fake_frappe(db=db)))
			stack.enter_context(patch("erpnext_extensions.cheque_management.pdc_open_advance._", lambda s: s))
			out = get_pdc_open_advance_instrument("PDC-A3")
			self.assertEqual(out["open_amount"], 0.0)
			self.assertFalse(out["allocatable"])

	def test_multi_row_order_allocations_roll_up(self) -> None:
		with ExitStack() as stack:
			def _sql(query, params=None, as_dict=False):
				return [{"amt": 15000.0}]

			db = SimpleNamespace(
				get_value=lambda *a, **k: {
						"name": "PDC-A4",
						"allocation_mode": "advance",
						"cheque_amount": 20000.0,
						"recognition_je_posted": 1,
						"instrument_dead": 0,
						"instrument_dead_reason": None,
					},
				sql=_sql,
				table_exists=lambda *a, **k: False,
			)
			stack.enter_context(patch("erpnext_extensions.cheque_management.pdc_open_advance.frappe", _fake_frappe(db=db)))
			stack.enter_context(patch("erpnext_extensions.cheque_management.pdc_open_advance._", lambda s: s))
			out = get_pdc_open_advance_by_order("PDC-A4", "Sales Order", "SO-1")
			self.assertEqual(out["bucket_gross"], 15000.0)
			self.assertEqual(out["open_amount"], 15000.0)

	def test_non_advance_pdc_rejected(self) -> None:
		with ExitStack() as stack:
			db = SimpleNamespace(
				get_value=lambda *a, **k: {
						"name": "PDC-N1",
						"allocation_mode": "direct_settlement",
						"cheque_amount": 1000.0,
						"recognition_je_posted": 1,
						"instrument_dead": 0,
						"instrument_dead_reason": None,
					},
				sql=lambda *a, **k: [],
				table_exists=lambda *a, **k: False,
			)
			stack.enter_context(patch("erpnext_extensions.cheque_management.pdc_open_advance.frappe", _fake_frappe(db=db)))
			stack.enter_context(patch("erpnext_extensions.cheque_management.pdc_open_advance._", lambda s: s))
			with self.assertRaises(ValidationError):
				is_pdc_advance_allocatable("PDC-N1")

	def test_order_level_totals_roll_up_across_pdcs(self) -> None:
		with ExitStack() as stack:
			# 2 PDCs in advance mode with allocations; one is not recognized (ignored)
			pdc_rows = [
				{"pdc": "PDC-X1", "cheque_amount": 1000.0, "recognition_je_posted": 1, "instrument_dead": 0, "bucket_gross": 600.0},
				{"pdc": "PDC-X2", "cheque_amount": 1000.0, "recognition_je_posted": 1, "instrument_dead": 0, "bucket_gross": 400.0},
				{"pdc": "PDC-X3", "cheque_amount": 1000.0, "recognition_je_posted": 0, "instrument_dead": 0, "bucket_gross": 999.0},
			]

			def _sql_side_effect(query, params=None, as_dict=False):
				q = " ".join((query or "").split())
				if "FROM `tabPost Dated Cheque` p" in q:
					return pdc_rows
				if "FROM `tabPDC Invoice Application`" in q:
					# posted 100 on X1; reversed 25 on X2
					return [
						{"pdc": "PDC-X1", "application_status": "posted", "amt": 100.0},
						{"pdc": "PDC-X2", "application_status": "reversed", "amt": 25.0},
					]
				return []

			db = SimpleNamespace(get_value=lambda *a, **k: None, sql=_sql_side_effect, table_exists=lambda *a, **k: True)
			stack.enter_context(patch("erpnext_extensions.cheque_management.pdc_open_advance.frappe", _fake_frappe(db=db)))
			stack.enter_context(patch("erpnext_extensions.cheque_management.pdc_open_advance._", lambda s: s))
			out = get_open_advance_for_order("Purchase Order", "PO-1")
			# open = (600 - 100) + (400 - 0 + 25) = 925
			self.assertEqual(out["open_amount"], 925.0)
			self.assertEqual(out["pdc_count"], 2)

	def test_posted_applications_reduce_instrument_open(self) -> None:
		with ExitStack() as stack:
			def _sql_side_effect(query, params=None, as_dict=False):
				q = " ".join((query or "").split())
				if "FROM `tabPDC Invoice Application`" in q and "WHERE post_dated_cheque = %s" in q:
					return [{"application_status": "posted", "amt": 250.0}]
				return []

			db = SimpleNamespace(
				get_value=lambda *a, **k: {
						"name": "PDC-R1",
						"allocation_mode": "advance",
						"cheque_amount": 1000.0,
						"recognition_je_posted": 1,
						"instrument_dead": 0,
						"instrument_dead_reason": None,
					},
				sql=_sql_side_effect,
				table_exists=lambda *a, **k: True,
			)
			stack.enter_context(patch("erpnext_extensions.cheque_management.pdc_open_advance.frappe", _fake_frappe(db=db)))
			stack.enter_context(patch("erpnext_extensions.cheque_management.pdc_open_advance._", lambda s: s))
			out = get_pdc_open_advance_instrument("PDC-R1")
			self.assertEqual(out["recognized_gross"], 1000.0)
			self.assertEqual(out["applied_amount"], 250.0)
			self.assertEqual(out["open_amount"], 750.0)

	def test_posted_applications_reduce_order_bucket_open(self) -> None:
		with ExitStack() as stack:
			def _sql_side_effect(query, params=None, as_dict=False):
				q = " ".join((query or "").split())
				if "FROM `tabPDC Allocation`" in q:
					return [{"amt": 600.0}]
				if "FROM `tabPDC Invoice Application`" in q and "order_doctype = %s" in q:
					return [
						{"application_status": "posted", "amt": 400.0},
						{"application_status": "reversed", "amt": 50.0},
					]
				return []

			db = SimpleNamespace(
				get_value=lambda *a, **k: {
						"name": "PDC-R2",
						"allocation_mode": "advance",
						"cheque_amount": 1000.0,
						"recognition_je_posted": 1,
						"instrument_dead": 0,
						"instrument_dead_reason": None,
					},
				sql=_sql_side_effect,
				table_exists=lambda *a, **k: True,
			)
			stack.enter_context(patch("erpnext_extensions.cheque_management.pdc_open_advance.frappe", _fake_frappe(db=db)))
			stack.enter_context(patch("erpnext_extensions.cheque_management.pdc_open_advance._", lambda s: s))
			out = get_pdc_open_advance_by_order("PDC-R2", "Purchase Order", "PO-1")
			# open = 600 - 400 + 50 = 250
			self.assertEqual(out["bucket_gross"], 600.0)
			self.assertEqual(out["applied_amount"], 400.0)
			self.assertEqual(out["reversed_amount"], 50.0)
			self.assertEqual(out["open_amount"], 250.0)

