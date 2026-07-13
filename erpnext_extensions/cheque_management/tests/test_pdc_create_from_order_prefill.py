from __future__ import annotations

import unittest
from unittest.mock import patch

import frappe
from frappe.exceptions import ValidationError

import erpnext_extensions.cheque_management.pdc_create_from_source as pdc_src
from erpnext_extensions.cheque_management.pdc_allocation import ALLOCATION_MODE_ADVANCE


class _ThrowCtx:
	"""Patch frappe.throw to raise ValidationError in bare unittest."""

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


class TestPdcCreateFromOrderPrefill(unittest.TestCase):
	def test_create_from_submitted_purchase_order_seeds_advance_pdc(self):
		def _get_value(dt, nm, fields, **kw):
			# Guardrail: PO path must not query SO-only `customer` field.
			if dt == "Purchase Order" and isinstance(fields, list) and "customer" in fields:
				raise AssertionError("Purchase Order prefill must not query `customer` field")
			if dt == "Purchase Order" and isinstance(fields, list):
				return {
					"docstatus": 1,
					"company": "_TC",
					"currency": "INR",
					"supplier": "SUP-1",
					"customer": None,
					"grand_total": 1000.0,
					"advance_paid": 200.0,
				}
			return None

		fake_db = type(
			"DB",
			(),
			{
				"exists": staticmethod(lambda dt, nm: True),
				"get_value": staticmethod(_get_value),
			},
		)()
		fake_frappe = type("F", (), {"db": fake_db, "has_permission": staticmethod(lambda *a, **k: True)})()

		with (
			_ThrowCtx(),
			patch.object(pdc_src, "frappe", fake_frappe),
			patch(
				"erpnext_extensions.cheque_management.pdc_create_from_source.get_order_remaining_advance_capacity",
				return_value=10_000.0,
			),
		):
			out = pdc_src.prepare_post_dated_cheque_prefill_from_order("Purchase Order", "PO-1")

		self.assertTrue(out.get("can_create"))
		prefill = out.get("prefill") or {}
		self.assertEqual(prefill.get("allocation_mode"), ALLOCATION_MODE_ADVANCE)
		self.assertEqual(prefill.get("company"), "_TC")
		self.assertEqual(prefill.get("currency"), "INR")
		self.assertEqual(prefill.get("party_type"), "Supplier")
		self.assertEqual(prefill.get("party"), "SUP-1")
		self.assertEqual(prefill.get("reference_doctype"), "Purchase Order")
		self.assertEqual(prefill.get("reference_name"), "PO-1")
		self.assertEqual(len(prefill.get("allocations") or []), 1)
		row = (prefill.get("allocations") or [None])[0] or {}
		self.assertEqual(row.get("allocation_mode"), ALLOCATION_MODE_ADVANCE)
		self.assertEqual(row.get("reference_doctype"), "Purchase Order")
		self.assertEqual(row.get("reference_name"), "PO-1")
		self.assertEqual(row.get("company"), "_TC")
		self.assertEqual(row.get("party_type"), "Supplier")
		self.assertEqual(row.get("party"), "SUP-1")
		self.assertFalse(row.get("source_doctype"))
		self.assertFalse(row.get("source_name"))

	def test_create_from_submitted_sales_order_seeds_advance_pdc(self):
		def _get_value(dt, nm, fields, **kw):
			# Guardrail: SO path must not query PO-only `supplier` field.
			if dt == "Sales Order" and isinstance(fields, list) and "supplier" in fields:
				raise AssertionError("Sales Order prefill must not query `supplier` field")
			if dt == "Sales Order" and isinstance(fields, list):
				return {
					"docstatus": 1,
					"company": "_TC",
					"currency": "INR",
					"supplier": None,
					"customer": "CUST-1",
					"grand_total": 500.0,
					"advance_paid": 0.0,
				}
			return None

		fake_db = type(
			"DB",
			(),
			{
				"exists": staticmethod(lambda dt, nm: True),
				"get_value": staticmethod(_get_value),
			},
		)()
		fake_frappe = type("F", (), {"db": fake_db, "has_permission": staticmethod(lambda *a, **k: True)})()

		with (
			_ThrowCtx(),
			patch.object(pdc_src, "frappe", fake_frappe),
			patch(
				"erpnext_extensions.cheque_management.pdc_create_from_source.get_order_remaining_advance_capacity",
				return_value=10_000.0,
			),
		):
			out = pdc_src.prepare_post_dated_cheque_prefill_from_order("Sales Order", "SO-1")

		self.assertTrue(out.get("can_create"))
		prefill = out.get("prefill") or {}
		self.assertEqual(prefill.get("allocation_mode"), ALLOCATION_MODE_ADVANCE)
		self.assertEqual(prefill.get("party_type"), "Customer")
		self.assertEqual(prefill.get("party"), "CUST-1")
		row = (prefill.get("allocations") or [None])[0] or {}
		self.assertEqual(row.get("reference_doctype"), "Sales Order")
		self.assertEqual(row.get("reference_name"), "SO-1")
		self.assertFalse(row.get("source_doctype"))
		self.assertFalse(row.get("source_name"))

	def test_draft_or_cancelled_orders_rejected(self):
		def _get_value(dt, nm, fields, **kw):
			# Guardrail: doctype-aware field selection even in rejection paths.
			if dt == "Sales Order" and isinstance(fields, list) and "supplier" in fields:
				raise AssertionError("Sales Order prefill must not query `supplier` field")
			if dt == "Purchase Order" and isinstance(fields, list) and "customer" in fields:
				raise AssertionError("Purchase Order prefill must not query `customer` field")
			if isinstance(fields, list):
				return {
					"docstatus": 0 if nm == "PO-DRAFT" else 2,
					"company": "_TC",
					"currency": "INR",
					"supplier": "SUP-1" if dt == "Purchase Order" else None,
					"customer": "CUST-1" if dt == "Sales Order" else None,
					"grand_total": 100.0,
					"advance_paid": 0.0,
				}
			return None

		fake_db = type(
			"DB",
			(),
			{
				"exists": staticmethod(lambda dt, nm: True),
				"get_value": staticmethod(_get_value),
			},
		)()
		fake_frappe = type("F", (), {"db": fake_db, "has_permission": staticmethod(lambda *a, **k: True)})()

		with (
			_ThrowCtx(),
			patch.object(pdc_src, "frappe", fake_frappe),
			patch(
				"erpnext_extensions.cheque_management.pdc_create_from_source.get_order_remaining_advance_capacity",
				return_value=10_000.0,
			),
		):
			out_draft = pdc_src.prepare_post_dated_cheque_prefill_from_order("Purchase Order", "PO-DRAFT")
			out_cancel = pdc_src.prepare_post_dated_cheque_prefill_from_order("Sales Order", "SO-CANCEL")

		self.assertFalse(out_draft.get("can_create"))
		self.assertFalse(out_cancel.get("can_create"))
