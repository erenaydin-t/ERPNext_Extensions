# Copyright (c) 2026, Farbod Siyahpoosh and contributors
# For license information, please see license.txt

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.exceptions import ValidationError

from erpnext_extensions.cheque_management import payment_entry_pdc_validation as pe_val
from erpnext_extensions.cheque_management.pdc_payment_request_eligibility import (
	validate_payment_request_invoice_ceiling_on_save,
)
from erpnext_extensions.cheque_management.pdc_settlement_capacity import validate_invoice_pr_issuance_ceiling


class _ThrowCtx:
	"""Patch frappe.throw to raise ValidationError in bare unittest."""

	def __enter__(self):
		self._p = patch.object(
			frappe, "throw", side_effect=lambda msg, *a, **k: (_ for _ in ()).throw(ValidationError(msg))
		)
		self._p.start()
		return self

	def __exit__(self, exc_type, exc, tb):
		self._p.stop()
		return False


class TestSettlementContractValidations(unittest.TestCase):
	def test_payment_entry_blocks_over_allocation_to_payment_request(self):
		doc = SimpleNamespace(
			doctype="Payment Entry",
			name="PE-1",
			docstatus=0,
			payment_type="Receive",
			references=[
				SimpleNamespace(
					reference_doctype="Sales Invoice",
					reference_name="SINV-1",
					allocated_amount=50,
					payment_request="PR-1",
				),
				SimpleNamespace(
					reference_doctype="Sales Invoice",
					reference_name="SINV-2",
					allocated_amount=60,
					payment_request="PR-1",
				),
			],
		)
		with _ThrowCtx(), patch.object(pe_val, "get_pr_remaining_capacity", return_value=80.0):
			with self.assertRaises(ValidationError):
				pe_val.validate_payment_entry_against_pdc_settlement(doc)

	def test_payment_entry_allows_allocation_within_payment_request_capacity(self):
		doc = SimpleNamespace(
			doctype="Payment Entry",
			name="PE-1",
			docstatus=0,
			payment_type="Receive",
			references=[
				SimpleNamespace(
					reference_doctype="Sales Invoice",
					reference_name="SINV-1",
					allocated_amount=50,
					payment_request="PR-1",
				),
			],
		)
		with _ThrowCtx(), patch.object(pe_val, "get_pr_remaining_capacity", return_value=80.0):
			pe_val.validate_payment_entry_against_pdc_settlement(doc)

	def test_payment_request_submit_blocks_multi_pr_exceeding_invoice_total_basis(self):
		pr = SimpleNamespace(
			doctype="Payment Request",
			name="PR-NEW",
			reference_doctype="Sales Invoice",
			reference_name="SINV-1",
			grand_total=20.0,
			workflow_state="Approved",
		)
		with (
			_ThrowCtx(),
			patch.object(
				frappe.db,
				"get_value",
				return_value=0,  # is_return=0
			),
			patch(
				"erpnext_extensions.cheque_management.pdc_settlement_capacity.get_invoice_total_basis",
				return_value=100.0,
			),
			patch(
				"erpnext_extensions.cheque_management.pdc_settlement_capacity.sum_submitted_pr_totals_for_invoice",
				return_value=90.0,
			),
			patch(
				"erpnext_extensions.cheque_management.pdc_payment_request_eligibility.is_payment_request_settlement_eligible",
				return_value=True,
			),
		):
			with self.assertRaises(ValidationError):
				validate_invoice_pr_issuance_ceiling(pr)

	def test_payment_request_submit_allows_multi_pr_within_invoice_total_basis(self):
		pr = SimpleNamespace(
			doctype="Payment Request",
			name="PR-NEW",
			reference_doctype="Sales Invoice",
			reference_name="SINV-1",
			grand_total=10.0,
			workflow_state="Approved",
		)
		with (
			_ThrowCtx(),
			patch.object(
				frappe.db,
				"get_value",
				return_value=0,
			),
			patch(
				"erpnext_extensions.cheque_management.pdc_settlement_capacity.get_invoice_total_basis",
				return_value=100.0,
			),
			patch(
				"erpnext_extensions.cheque_management.pdc_settlement_capacity.sum_submitted_pr_totals_for_invoice",
				return_value=90.0,
			),
			patch(
				"erpnext_extensions.cheque_management.pdc_payment_request_eligibility.is_payment_request_settlement_eligible",
				return_value=True,
			),
		):
			validate_invoice_pr_issuance_ceiling(pr)

	def test_payment_request_submit_blocks_against_return_invoice(self):
		pr = SimpleNamespace(
			doctype="Payment Request",
			name="PR-NEW",
			reference_doctype="Purchase Invoice",
			reference_name="PINV-1",
			grand_total=10.0,
			workflow_state="Approved",
		)
		with (
			_ThrowCtx(),
			patch.object(frappe.db, "get_value", return_value=1),
			patch(
				"erpnext_extensions.cheque_management.pdc_payment_request_eligibility.is_payment_request_settlement_eligible",
				return_value=True,
			),
		):
			with self.assertRaises(ValidationError):
				validate_invoice_pr_issuance_ceiling(pr)

	def test_payment_request_validate_skips_ceiling_when_not_settlement_eligible(self):
		pr = SimpleNamespace(
			doctype="Payment Request",
			name="PR-NEW",
			reference_doctype="Sales Invoice",
			reference_name="SINV-1",
			grand_total=999.0,
			workflow_state="Draft",
		)
		with (
			_ThrowCtx(),
			patch(
				"erpnext_extensions.cheque_management.pdc_settlement_capacity.validate_invoice_pr_issuance_ceiling",
			) as m_ceiling,
		):
			with patch(
				"erpnext_extensions.cheque_management.pdc_payment_request_eligibility.is_payment_request_settlement_eligible",
				return_value=False,
			):
				validate_payment_request_invoice_ceiling_on_save(pr)
		m_ceiling.assert_not_called()
