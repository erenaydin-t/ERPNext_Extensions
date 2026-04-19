# Copyright (c) 2026, Farbod Siyahpoosh and contributors
# For license information, please see license.txt

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import frappe

from erpnext_extensions.cheque_management.pdc_settlement_summary import get_settlement_summary_for_reference


class TestPdcSettlementSummaryPaymentRequest(unittest.TestCase):
	"""``document_outstanding`` for Payment Request must not mirror stale DB ``outstanding_amount`` (often 0 on draft)."""

	def test_draft_pr_zero_db_outstanding_shows_full_unpaid(self):
		row = {
			"grand_total": 50000.0,
			"outstanding_amount": 0.0,
			"company": "Test Co",
			"currency": "SAR",
			"docstatus": 0,
			"workflow_state": "Draft",
		}
		meta = MagicMock()
		meta.has_field = lambda f: f in ("grand_total", "outstanding_amount")
		with patch.object(frappe.db, "exists", return_value=True), patch.object(
			frappe, "has_permission"
		), patch.object(frappe.db, "get_value", return_value=row), patch.object(
			frappe, "get_meta", return_value=meta
		), patch(
			"erpnext_extensions.cheque_management.pdc_settlement_summary.is_payment_request_settlement_eligible",
			return_value=False,
		):
			s = get_settlement_summary_for_reference("Payment Request", "ACC-PRQ-2026-00025")
		self.assertIsNotNone(s)
		self.assertEqual(s["document_outstanding"], 50000.0)
		self.assertEqual(s["ledger_outstanding"], 50000.0)
		self.assertEqual(s["remaining_balance"], 50000.0)
		self.assertEqual(s["payment_entry_amount"], 0.0)
		self.assertEqual(s["effective_pdc_amount_direct"], 0.0)

	def test_eligible_pr_zero_db_outstanding_matches_gt_minus_pe_pdc(self):
		row = {
			"grand_total": 100.0,
			"outstanding_amount": 0.0,
			"company": "Test Co",
			"currency": "SAR",
			"docstatus": 1,
			"workflow_state": "Approved",
		}
		meta = MagicMock()
		meta.has_field = lambda f: f in ("grand_total", "outstanding_amount")
		with patch.object(frappe.db, "exists", return_value=True), patch.object(
			frappe, "has_permission"
		), patch.object(frappe.db, "get_value", return_value=row), patch.object(
			frappe, "get_meta", return_value=meta
		), patch(
			"erpnext_extensions.cheque_management.pdc_settlement_summary.is_payment_request_settlement_eligible",
			return_value=True,
		), patch(
			"erpnext_extensions.cheque_management.pdc_settlement_summary.sum_payment_entry_allocations_to_payment_request",
			return_value=30.0,
		), patch(
			"erpnext_extensions.cheque_management.pdc_settlement_summary.sum_effective_pdc_allocations_to_reference",
			return_value=20.0,
		):
			s = get_settlement_summary_for_reference("Payment Request", "PR-1")
		self.assertIsNotNone(s)
		self.assertEqual(s["document_outstanding"], 50.0)
		self.assertEqual(s["ledger_outstanding"], 50.0)
		self.assertEqual(s["remaining_balance"], 50.0)
