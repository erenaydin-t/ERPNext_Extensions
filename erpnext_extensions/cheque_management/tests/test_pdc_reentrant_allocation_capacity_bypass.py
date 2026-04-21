from __future__ import annotations

import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.exceptions import ValidationError

from erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque import PostDatedCheque
from erpnext_extensions.cheque_management.pdc_allocation import (
	ALLOCATION_MODE_DIRECT,
	validate_pdc_allocation_rows,
)
from erpnext_extensions.cheque_management.pdc_workflow_state_machine import CHEQUE_DIRECTION_RECEIVABLE


def _pdc(**kwargs) -> PostDatedCheque:
	p = PostDatedCheque.__new__(PostDatedCheque)
	defaults: dict = {
		"name": "PDC-TEST-REENTRANT-1",
		"company": "_TC",
		"currency": "INR",
		"party_type": "Customer",
		"party": "C-1",
		"cheque_direction": CHEQUE_DIRECTION_RECEIVABLE,
		"workflow_state": "Registered",
		"allocation_mode": ALLOCATION_MODE_DIRECT,
		"cheque_amount": 20000.0,
		"allocations": [
			SimpleNamespace(
				allocation_mode=ALLOCATION_MODE_DIRECT,
				reference_doctype="Sales Invoice",
				reference_name="SINV-REENTRANT-1",
				currency="INR",
				amount=20000.0,
				party_type="Customer",
				party="C-1",
				company="_TC",
			)
		],
	}
	defaults.update(kwargs)
	for k, v in defaults.items():
		setattr(p, k, v)
	return p


class TestPDCReentrantAllocationCapacityBypass(unittest.TestCase):
	def _frappe_throw_as_exception(self):
		def _throw(msg, *args, **kwargs):
			raise ValidationError(msg)

		return patch.object(frappe, "_", lambda s: s), patch.object(frappe, "throw", side_effect=_throw)

	def test_normal_save_still_enforces_capacity(self) -> None:
		"""If invoice outstanding is 0, capacity validation must still block (no bypass flag)."""
		p = _pdc()
		snap = {"company": "_TC", "currency": "INR", "customer": "C-1", "docstatus": 1, "outstanding_amount": 0.0}

		with ExitStack() as stack:
			a, b = self._frappe_throw_as_exception()
			stack.enter_context(a)
			stack.enter_context(b)
			stack.enter_context(
				patch(
					"erpnext_extensions.cheque_management.pdc_allocation._read_sales_invoice_for_pdc_allocation",
					return_value=snap,
				)
			)
			# Avoid DB-backed helpers in bare unittest.
			stack.enter_context(patch("erpnext_extensions.cheque_management.pdc_allocation.get_invoice_ledger_outstanding", return_value=0.0))
			stack.enter_context(patch("erpnext_extensions.cheque_management.pdc_allocation.sum_effective_pdc_direct_to_invoice", return_value=0.0))
			stack.enter_context(patch("erpnext_extensions.cheque_management.pdc_allocation.sum_effective_pdc_via_pr_to_invoice", return_value=0.0))
			stack.enter_context(
				patch(
					"erpnext_extensions.cheque_management.pdc_allocation.get_receivable_sales_invoice_direct_settlement_remaining_capacity",
					return_value=0.0,
				)
			)
			with self.assertRaises(ValidationError):
				validate_pdc_allocation_rows(p)

	def test_internal_reentrant_save_bypasses_capacity_only_for_same_pdc(self) -> None:
		"""Simulate the internal post-JE self-save: invoice is already settled => outstanding 0; must not re-block."""
		p = _pdc()
		snap = {"company": "_TC", "currency": "INR", "customer": "C-1", "docstatus": 1, "outstanding_amount": 0.0}

		with ExitStack() as stack:
			a, b = self._frappe_throw_as_exception()
			stack.enter_context(a)
			stack.enter_context(b)
			stack.enter_context(
				patch(
					"erpnext_extensions.cheque_management.pdc_allocation._read_sales_invoice_for_pdc_allocation",
					return_value=snap,
				)
			)
			# Even if helpers say 0, bypass must skip capacity check.
			stack.enter_context(patch("erpnext_extensions.cheque_management.pdc_allocation.get_invoice_ledger_outstanding", return_value=0.0))
			stack.enter_context(patch("erpnext_extensions.cheque_management.pdc_allocation.sum_effective_pdc_direct_to_invoice", return_value=0.0))
			stack.enter_context(patch("erpnext_extensions.cheque_management.pdc_allocation.sum_effective_pdc_via_pr_to_invoice", return_value=0.0))
			stack.enter_context(
				patch(
					"erpnext_extensions.cheque_management.pdc_allocation.get_receivable_sales_invoice_direct_settlement_remaining_capacity",
					return_value=0.0,
				)
			)
			# Scoped bypass for this PDC only (matches production flag behavior).
			# Bare unittest has no bound frappe.flags LocalProxy; patch it to a simple namespace.
			with patch.object(frappe, "flags", SimpleNamespace(skip_pdc_allocation_capacity_validation_for_pdc=p.name)):
				# Should not raise even though outstanding/capacity are 0.
				validate_pdc_allocation_rows(p)

