from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.exceptions import ValidationError

import erpnext_extensions.cheque_management.pdc_invoice_advance_candidates as cand


class _ThrowCtx:
	def __enter__(self):
		self._p = patch.object(
			frappe,
			"throw",
			side_effect=lambda msg, *a, **k: (_ for _ in ()).throw(ValidationError(msg)),
		)
		self._p.start()
		return self

	def __exit__(self, exc_type, exc, tb):
		self._p.stop()
		return False


class TestPDCInvoiceAdvanceCandidates(unittest.TestCase):
	def test_invoice_without_order_link_returns_empty(self) -> None:
		fake_inv = SimpleNamespace(company="_TC", currency="INR", supplier="SUP-1", items=[])
		fake_frappe = SimpleNamespace(
			db=SimpleNamespace(exists=lambda *a, **k: True, sql=lambda *a, **k: [], table_exists=lambda *a, **k: False),
			get_doc=lambda *a, **k: fake_inv,
			throw=lambda msg, *a, **k: (_ for _ in ()).throw(ValidationError(msg)),
		)
		with _ThrowCtx(), patch.object(cand, "frappe", fake_frappe), patch.object(cand, "_", lambda s: s):
			out = cand.get_advance_pdc_candidates_for_invoice("Purchase Invoice", "PINV-1")
		self.assertEqual(out, [])

	def test_recognized_po_based_advance_appears_for_purchase_invoice(self) -> None:
		fake_inv = SimpleNamespace(
			company="_TC",
			currency="INR",
			supplier="SUP-1",
			items=[SimpleNamespace(purchase_order="PO-1")],
		)

		def _sql(q, params=None, as_dict=False):
			if "FROM `tabPost Dated Cheque`" in q:
				return [
					{"pdc": "PDC-A1", "pdc_currency": "INR", "cheque_amount": 1000.0, "recognition_je_posted": 1, "instrument_dead": 0, "bucket_gross": 600.0}
				]
			if "FROM `tabPDC Invoice Application`" in q:
				return [{"pdc": "PDC-A1", "application_status": "posted", "amt": 100.0}]
			return []

		fake_frappe = SimpleNamespace(
			db=SimpleNamespace(exists=lambda *a, **k: True, sql=_sql, table_exists=lambda *a, **k: True),
			get_doc=lambda *a, **k: fake_inv,
			throw=lambda msg, *a, **k: (_ for _ in ()).throw(ValidationError(msg)),
		)
		with _ThrowCtx(), patch.object(cand, "frappe", fake_frappe), patch.object(cand, "_", lambda s: s):
			out = cand.get_advance_pdc_candidates_for_invoice("Purchase Invoice", "PINV-1")
		self.assertEqual(len(out), 1)
		self.assertEqual(out[0]["post_dated_cheque"], "PDC-A1")
		self.assertEqual(out[0]["open_amount"], 500.0)

	def test_fully_consumed_bucket_does_not_appear(self) -> None:
		"""If posted applications fully consume the bucket, candidate list must be empty."""
		fake_inv = SimpleNamespace(
			company="_TC",
			currency="INR",
			supplier="SUP-1",
			items=[SimpleNamespace(purchase_order="PO-1")],
		)

		def _sql(q, params=None, as_dict=False):
			if "FROM `tabPost Dated Cheque`" in q:
				return [
					{
						"pdc": "PDC-FULL",
						"pdc_currency": "INR",
						"cheque_amount": 1000.0,
						"recognition_je_posted": 1,
						"instrument_dead": 0,
						"bucket_gross": 600.0,
					}
				]
			if "FROM `tabPDC Invoice Application`" in q:
				# Consume the whole bucket.
				return [{"pdc": "PDC-FULL", "application_status": "posted", "amt": 600.0}]
			return []

		fake_frappe = SimpleNamespace(
			db=SimpleNamespace(exists=lambda *a, **k: True, sql=_sql, table_exists=lambda *a, **k: True),
			get_doc=lambda *a, **k: fake_inv,
			throw=lambda msg, *a, **k: (_ for _ in ()).throw(ValidationError(msg)),
		)
		with _ThrowCtx(), patch.object(cand, "frappe", fake_frappe), patch.object(cand, "_", lambda s: s):
			out = cand.get_advance_pdc_candidates_for_invoice("Purchase Invoice", "PINV-1")
		self.assertEqual(out, [])

	def test_partial_consumption_appears_with_remaining_open(self) -> None:
		fake_inv = SimpleNamespace(
			company="_TC",
			currency="INR",
			customer="CUST-1",
			items=[SimpleNamespace(sales_order="SO-1")],
		)

		def _sql(q, params=None, as_dict=False):
			if "FROM `tabPost Dated Cheque`" in q:
				return [
					{
						"pdc": "PDC-PART",
						"pdc_currency": "INR",
						"cheque_amount": 1000.0,
						"recognition_je_posted": 1,
						"instrument_dead": 0,
						"bucket_gross": 500.0,
					}
				]
			if "FROM `tabPDC Invoice Application`" in q:
				return [{"pdc": "PDC-PART", "application_status": "posted", "amt": 125.0}]
			return []

		fake_frappe = SimpleNamespace(
			db=SimpleNamespace(exists=lambda *a, **k: True, sql=_sql, table_exists=lambda *a, **k: True),
			get_doc=lambda *a, **k: fake_inv,
			throw=lambda msg, *a, **k: (_ for _ in ()).throw(ValidationError(msg)),
		)
		with _ThrowCtx(), patch.object(cand, "frappe", fake_frappe), patch.object(cand, "_", lambda s: s):
			out = cand.get_advance_pdc_candidates_for_invoice("Sales Invoice", "SINV-1")
		self.assertEqual(len(out), 1)
		self.assertEqual(out[0]["post_dated_cheque"], "PDC-PART")
		self.assertEqual(out[0]["open_amount"], 375.0)

	def test_cancel_restores_open_via_reversed_rows(self) -> None:
		"""Reversed rows must add back to open (gross - posted + reversed)."""
		fake_inv = SimpleNamespace(
			company="_TC",
			currency="INR",
			supplier="SUP-1",
			items=[SimpleNamespace(purchase_order="PO-1")],
		)

		def _sql(q, params=None, as_dict=False):
			if "FROM `tabPost Dated Cheque`" in q:
				return [
					{
						"pdc": "PDC-RESTORE",
						"pdc_currency": "INR",
						"cheque_amount": 1000.0,
						"recognition_je_posted": 1,
						"instrument_dead": 0,
						"bucket_gross": 600.0,
					}
				]
			if "FROM `tabPDC Invoice Application`" in q:
				return [
					{"pdc": "PDC-RESTORE", "application_status": "posted", "amt": 600.0},
					{"pdc": "PDC-RESTORE", "application_status": "reversed", "amt": 600.0},
				]
			return []

		fake_frappe = SimpleNamespace(
			db=SimpleNamespace(exists=lambda *a, **k: True, sql=_sql, table_exists=lambda *a, **k: True),
			get_doc=lambda *a, **k: fake_inv,
			throw=lambda msg, *a, **k: (_ for _ in ()).throw(ValidationError(msg)),
		)
		with _ThrowCtx(), patch.object(cand, "frappe", fake_frappe), patch.object(cand, "_", lambda s: s):
			out = cand.get_advance_pdc_candidates_for_invoice("Purchase Invoice", "PINV-1")
		self.assertEqual(len(out), 1)
		self.assertEqual(out[0]["open_amount"], 600.0)

