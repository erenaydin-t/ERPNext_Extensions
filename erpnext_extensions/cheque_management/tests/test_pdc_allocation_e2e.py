# Copyright (c) 2026, Farbod Siyahpoosh and contributors
# For license information, please see license.txt

"""End-to-end style tests for **PDC Allocation** behaviour (summary amounts + validation; no DB vouchers).

Covers:

* Single-invoice, multi-invoice, partial, advance, and payment-request rows
* ``allocated_amount`` / ``unallocated_amount`` sync rules
* Validation rules from :meth:`PostDatedCheque._validate_allocations`
* Journal payload independence from allocation rows (no movement accounting from allocation edits alone)

Run from bench root::

    ./env/bin/python -m unittest erpnext_extensions.cheque_management.tests.test_pdc_allocation_e2e -v
"""

from __future__ import annotations

import unittest
from contextlib import ExitStack, contextmanager
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

import frappe
import erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque as pdc_mod
from erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque import (
	PostDatedCheque,
	build_pdc_journal_entry_data,
)
import erpnext_extensions.cheque_management.pdc_settlement_capacity as pdc_cap
from erpnext_extensions.cheque_management import pdc_allocation as pdc_alloc
from erpnext_extensions.cheque_management.pdc_allocation import ALLOCATION_MODE_ADVANCE, ALLOCATION_MODE_DIRECT
from erpnext_extensions.cheque_management.pdc_workflow_state_machine import (
	CHEQUE_DIRECTION_PAYABLE,
	CHEQUE_DIRECTION_RECEIVABLE,
	WORKFLOW_DRAFT,
	WORKFLOW_ISSUED,
	WORKFLOW_REGISTERED,
	WORKFLOW_SENT_TO_BANK,
)
from frappe.exceptions import ValidationError

_SNAP_SI = {
	"company": "_TC",
	"currency": "INR",
	"customer": "C-1",
	"docstatus": 1,
	"outstanding_amount": 1_000_000.0,
}
_SNAP_PI = {
	"company": "_TC",
	"currency": "INR",
	"supplier": "SUP-1",
	"docstatus": 1,
	"outstanding_amount": 1_000_000.0,
}
_SNAP_PR_IN = {
	"company": "_TC",
	"currency": "INR",
	"party_type": "Customer",
	"party": "C-1",
	"payment_request_type": "Inward",
	"docstatus": 1,
	"workflow_state": "Approved",
	"outstanding_amount": 1_000_000.0,
	"status": "Requested",
}
_SNAP_PR_OUT = {
	"company": "_TC",
	"currency": "INR",
	"party_type": "Supplier",
	"party": "SUP-1",
	"payment_request_type": "Outward",
	"docstatus": 1,
	"workflow_state": "Approved",
	"outstanding_amount": 1_000_000.0,
	"status": "Requested",
}
_SNAP_SO = {
	"company": "_TC",
	"currency": "INR",
	"customer": "C-1",
	"docstatus": 1,
	"status": "To Deliver",
}
_SNAP_PO = {
	"company": "_TC",
	"currency": "INR",
	"supplier": "SUP-1",
	"docstatus": 1,
	"status": "To Receive",
}

POSTING = date(2026, 9, 1)
_BANK_GL = "ACC-BANK"
_SETTINGS: dict = {
	"default_cheques_in_hand_account": "ACC-CIH",
	"default_cheques_in_clearing_account": "ACC-CLR",
	"default_payable_cheque_account": "ACC-POOL",
	"default_protested_account": "ACC-PROT",
	"default_endorsement_account": None,
}


def _alloc_row(
	amount: float,
	allocation_mode: str,
	reference_doctype: str | None = None,
	reference_name: str | None = None,
	*,
	company: str | None = None,
	party_type: str | None = None,
	party: str | None = None,
	source_doctype: str | None = None,
	source_name: str | None = None,
) -> SimpleNamespace:
	return SimpleNamespace(
		amount=amount,
		allocation_mode=allocation_mode,
		reference_doctype=reference_doctype,
		reference_name=reference_name,
		company=company or "_TC",
		party_type=party_type or "Customer",
		party=party or "C-1",
		currency="INR",
		source_doctype=source_doctype,
		source_name=source_name,
	)


def _pdc(**kwargs) -> PostDatedCheque:
	"""Minimal PDC instance for allocation helpers (no DB, no full ``validate``)."""
	p = PostDatedCheque.__new__(PostDatedCheque)
	defaults: dict = {
		"cheque_amount": 1000.0,
		"cheque_direction": CHEQUE_DIRECTION_RECEIVABLE,
		"workflow_state": WORKFLOW_REGISTERED,
		"company": "_TC",
		"currency": "INR",
		"name": "PDC-TEST-1",
		"party_type": "Customer",
		"party": "C-1",
		"allocation_mode": ALLOCATION_MODE_DIRECT,
		"allocation_mode_locked": 0,
		"allocations": [],
		"allocated_amount": 0.0,
		"unallocated_amount": 1000.0,
	}
	defaults.update(kwargs)
	for k, v in defaults.items():
		setattr(p, k, v)
	return p


@contextmanager
def _frappe_messages_identity():
	"""Bare unittest has no bound ``frappe.local``; bypass ``msgprint`` inside ``frappe.throw``."""
	def _throw(msg, *args, **kwargs):
		raise ValidationError(msg)

	with patch.object(frappe, "_", lambda s: s), patch.object(frappe, "throw", side_effect=_throw):
		yield


def _allocation_ref_patches(*, payment_request_snapshot=None):
	"""DB-backed allocation checks are mocked (unit tests run without voucher rows)."""
	pr = payment_request_snapshot if payment_request_snapshot is not None else _SNAP_PR_IN
	return (
		patch.object(pdc_alloc, "_read_sales_invoice_for_pdc_allocation", return_value=_SNAP_SI),
		patch.object(pdc_alloc, "_read_purchase_invoice_for_pdc_allocation", return_value=_SNAP_PI),
		patch.object(pdc_alloc, "_read_payment_request_for_pdc_allocation", return_value=pr),
		patch.object(pdc_alloc, "_read_sales_order_for_pdc_allocation", return_value=_SNAP_SO),
		patch.object(pdc_alloc, "_read_purchase_order_for_pdc_allocation", return_value=_SNAP_PO),
		patch.object(pdc_alloc, "get_pr_remaining_capacity", return_value=1_000_000.0),
		patch.object(pdc_alloc, "get_invoice_remaining_capacity", return_value=1_000_000.0),
		patch.object(pdc_alloc, "get_receivable_sales_invoice_direct_settlement_remaining_capacity", return_value=1_000_000.0),
		# Advance-mode order ceiling is DB-backed; bare unittest has no site/db.
		patch.object(pdc_alloc, "get_order_remaining_advance_capacity", return_value=1_000_000.0),
		# Diagnostic path calls PL for SI rows; bare unittest has no frappe.db / site.
		patch.object(pdc_alloc, "get_invoice_ledger_outstanding", return_value=0.0),
		# SI trace path sums pending PDC rows via DB; no voucher rows in these unit tests.
		patch.object(pdc_alloc, "sum_effective_pdc_direct_to_invoice", return_value=0.0),
		patch.object(pdc_alloc, "sum_effective_pdc_via_pr_to_invoice", return_value=0.0),
	)


def _sync_and_validate(p: PostDatedCheque, **kw) -> None:
	PostDatedCheque._sync_allocation_summary_amounts(p)
	pr_snap = kw.get("payment_request_snapshot")
	with ExitStack() as stack:
		stack.enter_context(_frappe_messages_identity())
		for c in _allocation_ref_patches(payment_request_snapshot=pr_snap):
			stack.enter_context(c)
		PostDatedCheque._validate_allocations(p)


def _validate_allocations_only(p: PostDatedCheque, **kw) -> None:
	with ExitStack() as stack:
		stack.enter_context(_frappe_messages_identity())
		for c in _allocation_ref_patches(**kw):
			stack.enter_context(c)
		PostDatedCheque._validate_allocations(p)


class TestPDCAllocationAmounts(unittest.TestCase):
	def test_single_invoice_full_allocation(self) -> None:
		p = _pdc(
			allocations=[
				_alloc_row(
					1000.0,
					ALLOCATION_MODE_DIRECT,
					"Sales Invoice",
					"SINV-001",
				),
			],
		)
		_sync_and_validate(p)
		self.assertEqual(p.allocated_amount, 1000.0)
		self.assertEqual(p.unallocated_amount, 0.0)

	def test_multi_invoice_allocation(self) -> None:
		p = _pdc(
			allocations=[
				_alloc_row(400.0, ALLOCATION_MODE_DIRECT, "Sales Invoice", "SINV-001"),
				_alloc_row(600.0, ALLOCATION_MODE_DIRECT, "Sales Invoice", "SINV-002"),
			],
		)
		_sync_and_validate(p)
		self.assertEqual(p.allocated_amount, 1000.0)
		self.assertEqual(p.unallocated_amount, 0.0)

	def test_partial_allocation(self) -> None:
		p = _pdc(
			cheque_amount=1000.0,
			allocations=[
				_alloc_row(350.0, ALLOCATION_MODE_DIRECT, "Sales Invoice", "SINV-001"),
			],
		)
		_sync_and_validate(p)
		self.assertEqual(p.allocated_amount, 350.0)
		self.assertEqual(p.unallocated_amount, 650.0)

	def test_advance_sales_order_allocation(self) -> None:
		p = _pdc(
			allocation_mode=ALLOCATION_MODE_ADVANCE,
			allocations=[
				_alloc_row(500.0, ALLOCATION_MODE_ADVANCE, "Sales Order", "SO-001"),
			],
		)
		_sync_and_validate(p)
		self.assertEqual(p.allocated_amount, 500.0)
		self.assertEqual(p.unallocated_amount, 500.0)

	def test_payment_request_allocation(self) -> None:
		p = _pdc(
			allocations=[
				_alloc_row(
					250.0,
					ALLOCATION_MODE_DIRECT,
					"Sales Invoice",
					"SINV-PR-1",
					source_doctype="Payment Request",
					source_name="PR-ALLOC-1",
				),
			],
		)
		with patch(
			"erpnext_extensions.cheque_management.pdc_payment_request_eligibility.is_payment_request_settlement_eligible",
			return_value=True,
		):
			_sync_and_validate(p)
		self.assertEqual(p.allocated_amount, 250.0)
		self.assertEqual(p.unallocated_amount, 750.0)

	def test_payable_multi_purchase_invoice_allocation(self) -> None:
		p = _pdc(
			cheque_direction=CHEQUE_DIRECTION_PAYABLE,
			party_type="Supplier",
			party="SUP-1",
			allocations=[
				_alloc_row(
					250.0,
					ALLOCATION_MODE_DIRECT,
					"Purchase Invoice",
					"PINV-001",
					party_type="Supplier",
					party="SUP-1",
				),
				_alloc_row(
					750.0,
					ALLOCATION_MODE_DIRECT,
					"Purchase Invoice",
					"PINV-002",
					party_type="Supplier",
					party="SUP-1",
				),
			],
		)
		_sync_and_validate(p)
		self.assertEqual(p.allocated_amount, 1000.0)
		self.assertEqual(p.unallocated_amount, 0.0)

	def test_allocation_effective_flags_receivable(self) -> None:
		"""Planning vs effective: Registered+ has effective allocation; Draft is planning-only."""
		d = _pdc(workflow_state=WORKFLOW_DRAFT)
		r = _pdc(workflow_state=WORKFLOW_REGISTERED)
		self.assertFalse(d.is_allocation_effective())
		self.assertTrue(r.is_allocation_effective())
		self.assertTrue(d.is_allocation_draft_only())
		self.assertFalse(r.is_allocation_draft_only())


class TestPDCAllocationValidation(unittest.TestCase):
	def test_zero_amount_rejected(self) -> None:
		p = _pdc(
			allocations=[_alloc_row(0.0, ALLOCATION_MODE_DIRECT, "Sales Invoice", "SINV-1")],
		)
		PostDatedCheque._sync_allocation_summary_amounts(p)
		with self.assertRaises(ValidationError):
			_validate_allocations_only(p)

	def test_reference_pair_incomplete_rejected(self) -> None:
		p = _pdc(
			allocations=[_alloc_row(100.0, ALLOCATION_MODE_DIRECT, "Sales Invoice", None)],
		)
		PostDatedCheque._sync_allocation_summary_amounts(p)
		with self.assertRaises(ValidationError):
			_validate_allocations_only(p)

	def test_total_exceeds_cheque_rejected_in_sync(self) -> None:
		p = _pdc(
			cheque_amount=100.0,
			allocations=[
				_alloc_row(60.0, ALLOCATION_MODE_DIRECT, "Sales Invoice", "A"),
				_alloc_row(50.0, ALLOCATION_MODE_DIRECT, "Sales Invoice", "B"),
			],
		)
		with _frappe_messages_identity(), self.assertRaises(ValidationError):
			PostDatedCheque._sync_allocation_summary_amounts(p)

	def test_total_exceeds_cheque_rejected_in_validate_allocations(self) -> None:
		# Same cap enforced in _validate_allocations (sum of row amounts).
		p = _pdc(
			cheque_amount=100.0,
			allocations=[
				_alloc_row(60.0, ALLOCATION_MODE_DIRECT, "Sales Invoice", "A"),
				_alloc_row(50.0, ALLOCATION_MODE_DIRECT, "Sales Invoice", "B"),
			],
		)
		p.allocated_amount = 110.0
		p.unallocated_amount = -10.0
		with self.assertRaises(ValidationError):
			_validate_allocations_only(p)

	def test_receivable_invoice_must_be_sales_invoice(self) -> None:
		p = _pdc(
			cheque_direction=CHEQUE_DIRECTION_RECEIVABLE,
			allocations=[
				_alloc_row(100.0, ALLOCATION_MODE_DIRECT, "Purchase Invoice", "PINV-1"),
			],
		)
		PostDatedCheque._sync_allocation_summary_amounts(p)
		with self.assertRaises(ValidationError):
			_validate_allocations_only(p)

	def test_payable_invoice_must_be_purchase_invoice(self) -> None:
		p = _pdc(
			cheque_direction=CHEQUE_DIRECTION_PAYABLE,
			party_type="Supplier",
			party="SUP-1",
			allocations=[
				_alloc_row(100.0, ALLOCATION_MODE_DIRECT, "Sales Invoice", "SINV-1"),
			],
		)
		PostDatedCheque._sync_allocation_summary_amounts(p)
		with self.assertRaises(ValidationError):
			_validate_allocations_only(p)

	def test_payment_request_requires_reference(self) -> None:
		p = _pdc(
			allocations=[_alloc_row(10.0, ALLOCATION_MODE_DIRECT, "Sales Invoice", None)],
		)
		PostDatedCheque._sync_allocation_summary_amounts(p)
		with self.assertRaises(ValidationError):
			_validate_allocations_only(p)

	def test_disallowed_reference_doctype_rejected(self) -> None:
		p = _pdc(
			allocations=[_alloc_row(10.0, ALLOCATION_MODE_DIRECT, "Journal Entry", "JE-1")],
		)
		PostDatedCheque._sync_allocation_summary_amounts(p)
		with self.assertRaises(ValidationError):
			_validate_allocations_only(p)

	def test_stock_entry_reference_rejected(self) -> None:
		p = _pdc(
			allocations=[_alloc_row(50.0, ALLOCATION_MODE_DIRECT, "Stock Entry", "SE-1")],
		)
		PostDatedCheque._sync_allocation_summary_amounts(p)
		with self.assertRaises(ValidationError):
			_validate_allocations_only(p)

	def test_payable_issued_skips_pdc_settlement_capacity_against_pi(self) -> None:
		"""Issued payable: register JE already settled PI; do not block when capacity helper returns zero."""
		p = _pdc(
			cheque_direction=CHEQUE_DIRECTION_PAYABLE,
			party_type="Supplier",
			party="SUP-1",
			workflow_state=WORKFLOW_ISSUED,
			allocations=[
				_alloc_row(
					1000.0,
					ALLOCATION_MODE_DIRECT,
					"Purchase Invoice",
					"PINV-1",
					party_type="Supplier",
					party="SUP-1",
				)
			],
		)
		PostDatedCheque._sync_allocation_summary_amounts(p)
		with ExitStack() as stack:
			stack.enter_context(_frappe_messages_identity())
			stack.enter_context(
				patch.object(pdc_alloc, "_read_purchase_invoice_for_pdc_allocation", return_value=_SNAP_PI)
			)
			stack.enter_context(patch.object(pdc_alloc, "get_invoice_remaining_capacity", return_value=0.0))
			PostDatedCheque._validate_allocations(p)

	def test_payable_draft_to_registered_save_skips_capacity_via_doc_before_save(self) -> None:
		"""Validate order: snapshot Draft → doc Registered still skips (register JE will settle)."""
		p = _pdc(
			cheque_direction=CHEQUE_DIRECTION_PAYABLE,
			party_type="Supplier",
			party="SUP-1",
			workflow_state=WORKFLOW_REGISTERED,
			allocations=[
				_alloc_row(
					1000.0,
					ALLOCATION_MODE_DIRECT,
					"Purchase Invoice",
					"PINV-1",
					party_type="Supplier",
					party="SUP-1",
				)
			],
		)
		p.get_doc_before_save = lambda: SimpleNamespace(workflow_state=WORKFLOW_DRAFT)
		PostDatedCheque._sync_allocation_summary_amounts(p)
		with ExitStack() as stack:
			stack.enter_context(_frappe_messages_identity())
			stack.enter_context(
				patch.object(pdc_alloc, "_read_purchase_invoice_for_pdc_allocation", return_value=_SNAP_PI)
			)
			stack.enter_context(patch.object(pdc_alloc, "get_invoice_remaining_capacity", return_value=0.0))
			PostDatedCheque._validate_allocations(p)

	def test_receivable_draft_to_registered_allows_si_with_positive_outstanding_even_if_ledger_capacity_helper_is_zero(self) -> None:
		"""Oracle parity: Draft → Registered should not fail due to pre-JE ledger capacity for Sales Invoice."""
		p = _pdc(
			cheque_direction=CHEQUE_DIRECTION_RECEIVABLE,
			party_type="Customer",
			party="C-1",
			cheque_amount=20000.0,
			workflow_state=WORKFLOW_REGISTERED,
			allocations=[
				_alloc_row(
					20000.0,
					ALLOCATION_MODE_DIRECT,
					"Sales Invoice",
					"SINV-1",
					party_type="Customer",
					party="C-1",
				)
			],
		)
		p.get_doc_before_save = lambda: SimpleNamespace(workflow_state=WORKFLOW_DRAFT)
		PostDatedCheque._sync_allocation_summary_amounts(p)
		snap = dict(_SNAP_SI)
		snap["outstanding_amount"] = 20000.0
		with ExitStack() as stack:
			stack.enter_context(_frappe_messages_identity())
			stack.enter_context(patch.object(pdc_alloc, "_read_sales_invoice_for_pdc_allocation", return_value=snap))
			# Payment Ledger can be 0 before Register JE; capacity must still follow invoice outstanding_amount + pending PDC math.
			stack.enter_context(patch.object(pdc_alloc, "get_invoice_ledger_outstanding", return_value=0.0))
			# ``from capacity import f`` binds names in pdc_allocation; patch both modules.
			stack.enter_context(patch.object(pdc_cap, "sum_effective_pdc_direct_to_invoice", return_value=0.0))
			stack.enter_context(patch.object(pdc_cap, "sum_effective_pdc_via_pr_to_invoice", return_value=0.0))
			stack.enter_context(patch.object(pdc_alloc, "sum_effective_pdc_direct_to_invoice", return_value=0.0))
			stack.enter_context(patch.object(pdc_alloc, "sum_effective_pdc_via_pr_to_invoice", return_value=0.0))
			PostDatedCheque._validate_allocations(p)

	def test_receivable_draft_to_registered_blocks_si_when_outstanding_is_zero(self) -> None:
		p = _pdc(
			cheque_direction=CHEQUE_DIRECTION_RECEIVABLE,
			party_type="Customer",
			party="C-1",
			cheque_amount=1.0,
			workflow_state=WORKFLOW_REGISTERED,
			allocations=[
				_alloc_row(
					1.0,
					ALLOCATION_MODE_DIRECT,
					"Sales Invoice",
					"SINV-1",
					party_type="Customer",
					party="C-1",
				)
			],
		)
		p.get_doc_before_save = lambda: SimpleNamespace(workflow_state=WORKFLOW_DRAFT)
		PostDatedCheque._sync_allocation_summary_amounts(p)
		snap = dict(_SNAP_SI)
		snap["outstanding_amount"] = 0.0
		with ExitStack() as stack:
			stack.enter_context(_frappe_messages_identity())
			stack.enter_context(patch.object(pdc_alloc, "_read_sales_invoice_for_pdc_allocation", return_value=snap))
			stack.enter_context(patch.object(pdc_alloc, "get_invoice_ledger_outstanding", return_value=0.0))
			stack.enter_context(patch.object(pdc_cap, "sum_effective_pdc_direct_to_invoice", return_value=0.0))
			stack.enter_context(patch.object(pdc_cap, "sum_effective_pdc_via_pr_to_invoice", return_value=0.0))
			stack.enter_context(patch.object(pdc_alloc, "sum_effective_pdc_direct_to_invoice", return_value=0.0))
			stack.enter_context(patch.object(pdc_alloc, "sum_effective_pdc_via_pr_to_invoice", return_value=0.0))
			with self.assertRaises(ValidationError):
				PostDatedCheque._validate_allocations(p)


class TestPDCAllocationDoesNotDriveJournalPayloads(unittest.TestCase):
	"""Allocation rows are informational for movement JEs; changing them must not change JE payloads."""

	def _movement_doc(self, **allocations_kw) -> SimpleNamespace:
		base = dict(
			company="_TC",
			cheque_direction=CHEQUE_DIRECTION_RECEIVABLE,
			party_type="Customer",
			party="CUST-1",
			cheque_amount=1000.0,
			cheque_no="ALLOC-JE-1",
			account_paid_to="ACC-CIH",
			account_paid_from="ACC-AR-DOC",
			bank_account="BA-COMP",
			holder_party_type=None,
			holder_party=None,
		)
		base.update(allocations_kw)
		return SimpleNamespace(**base)

	def test_register_je_identical_regardless_of_allocations(self) -> None:
		"""When SI settlement slices are not produced (legacy path), Register JE ignores allocation rows.

		If :func:`receivable_sales_invoice_settlement_slices` returns invoice splits, Draft→Registered
		builds multi-line SI references; that path is not asserted here.
		"""
		heavy = self._movement_doc(
			allocations=[
				_alloc_row(400.0, ALLOCATION_MODE_DIRECT, "Sales Invoice", "S-1"),
				_alloc_row(600.0, ALLOCATION_MODE_DIRECT, "Sales Invoice", "S-2"),
			],
		)
		none = self._movement_doc(allocations=[])
		with (
			patch.object(pdc_mod, "_get_pdc_settings_for_company", return_value=dict(_SETTINGS)),
			patch.object(pdc_mod, "_get_party_account_or_company_default", return_value="ACC-AR-RES"),
			patch.object(pdc_mod, "_pdc_bank_gl_account", return_value=_BANK_GL),
			patch.object(pdc_mod, "receivable_sales_invoice_settlement_slices", return_value=None),
			patch.object(pdc_mod, "frappe") as mf,
		):
			mf._ = lambda s: s
			je_a = build_pdc_journal_entry_data(heavy, WORKFLOW_DRAFT, WORKFLOW_REGISTERED, POSTING)
			je_b = build_pdc_journal_entry_data(none, WORKFLOW_DRAFT, WORKFLOW_REGISTERED, POSTING)
		self.assertEqual(je_a, je_b)
		self.assertIsNotNone(je_a)

	def test_subsequent_movement_jes_also_ignore_allocations(self) -> None:
		"""Allocation edits alone must not change movement payloads at any workflow edge."""
		heavy = self._movement_doc(
			allocations=[_alloc_row(1000.0, ALLOCATION_MODE_DIRECT, "Sales Invoice", "S-9")],
		)
		none = self._movement_doc(allocations=[])
		with (
			patch.object(pdc_mod, "_get_pdc_settings_for_company", return_value=dict(_SETTINGS)),
			patch.object(pdc_mod, "_get_party_account_or_company_default", return_value="ACC-AR-RES"),
			patch.object(pdc_mod, "_pdc_bank_gl_account", return_value=_BANK_GL),
			patch.object(pdc_mod, "frappe") as mf,
		):
			mf._ = lambda s: s
			j_stb_a = build_pdc_journal_entry_data(
				heavy, WORKFLOW_REGISTERED, WORKFLOW_SENT_TO_BANK, POSTING
			)
			j_stb_b = build_pdc_journal_entry_data(
				none, WORKFLOW_REGISTERED, WORKFLOW_SENT_TO_BANK, POSTING
			)
		self.assertEqual(j_stb_a, j_stb_b)


if __name__ == "__main__":
	unittest.main()
