# Copyright (c) 2026, Farbod Siyahpoosh and contributors
# For license information, please see license.txt

"""Runtime-parity tests: Receivable Sales Invoice capacity uses invoice ``outstanding_amount``, not Payment Ledger."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import erpnext_extensions.cheque_management.pdc_settlement_capacity as cap


class TestReceivableSalesInvoiceDirectSettlementCapacity(unittest.TestCase):
	def test_remaining_matches_snapshot_when_pending_zero(self):
		with patch.object(cap, "sum_effective_pdc_direct_to_invoice", return_value=0.0), patch.object(
			cap, "sum_effective_pdc_via_pr_to_invoice", return_value=0.0
		):
			v = cap.get_receivable_sales_invoice_direct_settlement_remaining_capacity(
				"SINV-1", invoice_outstanding_amount=20_000.0, exclude_pdc="PDC-SELF"
			)
		self.assertEqual(v, 20_000.0)

	def test_remaining_subtracts_pending_pdc_reservations(self):
		with patch.object(cap, "sum_effective_pdc_direct_to_invoice", return_value=5_000.0), patch.object(
			cap, "sum_effective_pdc_via_pr_to_invoice", return_value=2_000.0
		):
			v = cap.get_receivable_sales_invoice_direct_settlement_remaining_capacity(
				"SINV-1", invoice_outstanding_amount=20_000.0, exclude_pdc=None
			)
		self.assertEqual(v, 13_000.0)
