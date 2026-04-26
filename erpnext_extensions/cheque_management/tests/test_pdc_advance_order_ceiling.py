from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.exceptions import ValidationError

import erpnext_extensions.cheque_management.pdc_advance_order_capacity as cap
from erpnext_extensions.cheque_management.pdc_allocation import ALLOCATION_MODE_ADVANCE, validate_pdc_allocation_rows
from erpnext_extensions.cheque_management.pdc_workflow_state_machine import (
	CHEQUE_DIRECTION_PAYABLE,
	CHEQUE_DIRECTION_RECEIVABLE,
)


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


def _pdc(*, direction: str, party_type: str, party: str, company="_TC", currency="INR", name="PDC-1", allocations=None):
	return SimpleNamespace(
		name=name,
		company=company,
		currency=currency,
		party_type=party_type,
		party=party,
		cheque_direction=direction,
		allocation_mode=ALLOCATION_MODE_ADVANCE,
		allocations=allocations or [],
		cheque_amount=999999.0,
		workflow_state="Draft",
	)


def _alloc(order_dt, order_nm, amt, *, company="_TC", party_type="Supplier", party="SUP-1"):
 return SimpleNamespace(
		allocation_mode=ALLOCATION_MODE_ADVANCE,
		reference_doctype=order_dt,
		reference_name=order_nm,
		amount=amt,
		company=company,
		party_type=party_type,
		party=party,
		currency="INR",
		source_doctype=None,
		source_name=None,
 )


class TestAdvanceOrderCeiling(unittest.TestCase):
	def test_reserved_amount_excludes_dead_and_cancelled_and_self(self) -> None:
		# SQL is DB-backed; mock it.
		fake_frappe = SimpleNamespace(
			db=SimpleNamespace(
				get_value=lambda *a, **k: 1000.0,
				sql=lambda *a, **k: [{"amt": 600.0}],
			),
			throw=lambda msg, *a, **k: (_ for _ in ()).throw(ValidationError(msg)),
		)
		with _ThrowCtx(), patch.object(cap, "frappe", fake_frappe), patch.object(cap, "_", lambda s: s):
			rem = cap.get_order_remaining_advance_capacity("Purchase Order", "PO-1", exclude_pdc="PDC-SELF")
		self.assertEqual(rem, 400.0)

	def test_second_pdc_over_ceiling_blocked(self) -> None:
		doc = _pdc(
			direction=CHEQUE_DIRECTION_PAYABLE,
			party_type="Supplier",
			party="SUP-1",
			name="PDC-NEW",
			allocations=[_alloc("Purchase Order", "PO-1", 500.0)],
		)
		# Remaining capacity excluding self is 400 -> doc total 500 should block.
		with _ThrowCtx(), patch(
			"erpnext_extensions.cheque_management.pdc_allocation.get_order_remaining_advance_capacity",
			return_value=400.0,
		), patch(
			"erpnext_extensions.cheque_management.pdc_allocation._read_purchase_order_for_pdc_allocation",
			return_value={"company": "_TC", "currency": "INR", "supplier": "SUP-1", "docstatus": 1, "status": "To Receive"},
		):
			with self.assertRaises(ValidationError):
				validate_pdc_allocation_rows(doc)

	def test_self_edit_excluded_no_double_count(self) -> None:
		doc = _pdc(
			direction=CHEQUE_DIRECTION_RECEIVABLE,
			party_type="Customer",
			party="CUST-1",
			name="PDC-SELF",
			allocations=[_alloc("Sales Order", "SO-1", 400.0, party_type="Customer", party="CUST-1")],
		)
		with _ThrowCtx(), patch(
			"erpnext_extensions.cheque_management.pdc_allocation.get_order_remaining_advance_capacity",
			return_value=400.0,
		), patch(
			"erpnext_extensions.cheque_management.pdc_allocation._read_sales_order_for_pdc_allocation",
			return_value={"company": "_TC", "currency": "INR", "customer": "CUST-1", "docstatus": 1, "status": "To Deliver"},
		):
			# Should not raise.
			validate_pdc_allocation_rows(doc)

