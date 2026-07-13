# Copyright (c) 2026, ERPNext Extensions contributors

"""Integration tests for PDC workflow rollback (requires live site data)."""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from erpnext_extensions.cheque_management.pdc_workflow_rollback import (
	get_rollback_target_states,
	sql_verify_no_orphan_gl_for_pdc,
)


class TestPDCWorkflowRollbackIntegration(FrappeTestCase):
	def test_integration_placeholder_skipped_without_payable_pdc(self):
		"""Run full lifecycle rollback when a Payable PDC fixture exists on the site."""
		name = frappe.db.get_value(
			"Post Dated Cheque",
			{"cheque_direction": "Payable", "docstatus": 1, "workflow_state": "Cleared"},
			"name",
			order_by="modified desc",
		)
		if not name:
			self.skipTest("No submitted Cleared Payable PDC on site")
		targets = get_rollback_target_states(name)
		self.assertIn("Issued", targets)
		self.assertEqual(
			sql_verify_no_orphan_gl_for_pdc(name, []), {"gl_entry": 0, "payment_ledger_entry": 0}
		)
