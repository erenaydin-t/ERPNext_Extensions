# Copyright (c) 2026, ERPNext Extensions contributors

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.exceptions import ValidationError

from erpnext_extensions.cheque_management.accounting_rollback.pdc.plan import (
	_edges_to_undo,
	_filter_edges_at_or_after_baseline,
	build_pdc_rollback_plan,
)
from erpnext_extensions.cheque_management.pdc_opening_import_baseline import (
	infer_opening_import_baseline_state,
	resolve_opening_import_baseline_state,
)
from erpnext_extensions.cheque_management.pdc_workflow_rollback import get_rollback_target_states
from erpnext_extensions.cheque_management.pdc_workflow_state_machine import (
	CHEQUE_DIRECTION_PAYABLE,
	CHEQUE_DIRECTION_RECEIVABLE,
	WORKFLOW_CLEARED,
	WORKFLOW_DRAFT,
	WORKFLOW_ISSUED,
	WORKFLOW_REGISTERED,
	WORKFLOW_SENT_TO_BANK,
	get_allowed_next_workflow_states,
)


class TestCancelWorkflowRemoved(unittest.TestCase):
	def test_payable_issued_no_cancel_target(self):
		nxt = get_allowed_next_workflow_states(CHEQUE_DIRECTION_PAYABLE, WORKFLOW_ISSUED)
		self.assertNotIn("Cancelled", nxt)

	def test_receivable_registered_no_cancel_target(self):
		nxt = get_allowed_next_workflow_states(CHEQUE_DIRECTION_RECEIVABLE, WORKFLOW_REGISTERED)
		self.assertNotIn("Cancelled", nxt)


class TestOpeningImportRollbackEdges(unittest.TestCase):
	def test_filter_drops_pre_baseline_edges(self):
		edges = [
			(WORKFLOW_DRAFT, WORKFLOW_REGISTERED),
			(WORKFLOW_REGISTERED, WORKFLOW_ISSUED),
			(WORKFLOW_ISSUED, WORKFLOW_CLEARED),
		]
		out = _filter_edges_at_or_after_baseline(CHEQUE_DIRECTION_PAYABLE, edges, WORKFLOW_REGISTERED)
		self.assertEqual(
			out,
			[(WORKFLOW_REGISTERED, WORKFLOW_ISSUED), (WORKFLOW_ISSUED, WORKFLOW_CLEARED)],
		)

	def test_opening_edges_undo_skips_draft_register(self):
		pdc = SimpleNamespace(
			is_opening_import=1,
			opening_import_workflow_state=WORKFLOW_REGISTERED,
			cheque_direction=CHEQUE_DIRECTION_PAYABLE,
			workflow_state=WORKFLOW_CLEARED,
			name="PDC-TEST",
		)
		with patch(
			"erpnext_extensions.cheque_management.accounting_rollback.pdc.plan.index_journal_references",
			return_value={},
		):
			edges = _edges_to_undo(CHEQUE_DIRECTION_PAYABLE, WORKFLOW_CLEARED, WORKFLOW_REGISTERED, pdc=pdc)
		self.assertEqual(
			edges,
			[(WORKFLOW_ISSUED, WORKFLOW_CLEARED), (WORKFLOW_REGISTERED, WORKFLOW_ISSUED)],
		)


class TestOpeningImportRollbackTargets(unittest.TestCase):
	def _mock_pdc(self, **kw):
		base = dict(
			name="PDC-OI-1",
			cheque_direction=CHEQUE_DIRECTION_PAYABLE,
			workflow_state=WORKFLOW_REGISTERED,
			docstatus=1,
			is_opening_import=1,
			opening_import_workflow_state=WORKFLOW_REGISTERED,
		)
		base.update(kw)
		return SimpleNamespace(**base)

	@patch("erpnext_extensions.cheque_management.pdc_workflow_rollback.frappe.get_doc")
	def test_at_baseline_no_targets(self, get_doc):
		get_doc.return_value = self._mock_pdc(workflow_state=WORKFLOW_REGISTERED)
		self.assertEqual(get_rollback_target_states("PDC-OI-1"), [])

	@patch("erpnext_extensions.cheque_management.pdc_workflow_rollback.frappe.get_doc")
	def test_cleared_after_post_import_has_issued_and_registered(self, get_doc):
		get_doc.return_value = self._mock_pdc(workflow_state=WORKFLOW_CLEARED)
		targets = get_rollback_target_states("PDC-OI-1")
		self.assertIn(WORKFLOW_ISSUED, targets)
		self.assertIn(WORKFLOW_REGISTERED, targets)
		self.assertNotIn(WORKFLOW_DRAFT, targets)

	@patch("erpnext_extensions.cheque_management.pdc_workflow_rollback.frappe.get_doc")
	def test_sent_to_bank_baseline_no_rollback_to_registered(self, get_doc):
		get_doc.return_value = self._mock_pdc(
			cheque_direction=CHEQUE_DIRECTION_RECEIVABLE,
			workflow_state=WORKFLOW_SENT_TO_BANK,
			opening_import_workflow_state=WORKFLOW_SENT_TO_BANK,
		)
		self.assertEqual(get_rollback_target_states("PDC-OI-1"), [])

	@patch("erpnext_extensions.cheque_management.pdc_workflow_rollback.frappe.get_doc")
	def test_issued_baseline_at_issued_no_targets(self, get_doc):
		get_doc.return_value = self._mock_pdc(
			workflow_state=WORKFLOW_ISSUED,
			opening_import_workflow_state=WORKFLOW_ISSUED,
		)
		self.assertEqual(get_rollback_target_states("PDC-OI-1"), [])

	@patch("erpnext_extensions.cheque_management.pdc_workflow_rollback.frappe.get_doc")
	def test_issued_baseline_cleared_only_issued_target(self, get_doc):
		get_doc.return_value = self._mock_pdc(
			workflow_state=WORKFLOW_CLEARED,
			opening_import_workflow_state=WORKFLOW_ISSUED,
		)
		targets = get_rollback_target_states("PDC-OI-1")
		self.assertEqual(targets, [WORKFLOW_ISSUED])

	@patch("erpnext_extensions.cheque_management.pdc_workflow_rollback.frappe.get_doc")
	def test_cleared_baseline_at_cleared_no_targets(self, get_doc):
		get_doc.return_value = self._mock_pdc(
			workflow_state=WORKFLOW_CLEARED,
			opening_import_workflow_state=WORKFLOW_CLEARED,
		)
		self.assertEqual(get_rollback_target_states("PDC-OI-1"), [])

	@patch("erpnext_extensions.cheque_management.pdc_workflow_rollback.frappe.get_doc")
	def test_receivable_cleared_after_sent_to_bank_baseline(self, get_doc):
		get_doc.return_value = self._mock_pdc(
			cheque_direction=CHEQUE_DIRECTION_RECEIVABLE,
			workflow_state=WORKFLOW_CLEARED,
			opening_import_workflow_state=WORKFLOW_SENT_TO_BANK,
		)
		targets = get_rollback_target_states("PDC-OI-1")
		self.assertEqual(targets, [WORKFLOW_SENT_TO_BANK])
		self.assertNotIn(WORKFLOW_REGISTERED, targets)


class TestOpeningImportRollbackPlan(unittest.TestCase):
	def test_cleared_to_issued_plan_single_edge(self):
		pdc = SimpleNamespace(
			name="PDC-OI-PLAN",
			is_opening_import=1,
			opening_import_workflow_state=WORKFLOW_ISSUED,
			cheque_direction=CHEQUE_DIRECTION_PAYABLE,
			workflow_state=WORKFLOW_CLEARED,
			cheque_status="Cleared",
			docstatus=1,
			company="Test Co",
			cheque_no="123",
		)
		with (
			patch(
				"erpnext_extensions.cheque_management.accounting_rollback.pdc.plan.index_journal_references",
				return_value={
					(WORKFLOW_ISSUED, WORKFLOW_CLEARED): {
						"name": "ref1",
						"journal_entry": "JE-1",
						"pdc_transition_key": "PDC-OI-PLAN|Payable|Issued|Cleared",
						"purpose": "Payable Clear",
					}
				},
			),
			patch(
				"erpnext_extensions.cheque_management.accounting_rollback.pdc.plan.validate_rollback_blockers",
			),
		):
			plan = build_pdc_rollback_plan(pdc, WORKFLOW_ISSUED)
		self.assertEqual(len(plan.steps), 1)
		self.assertEqual(plan.steps[0].from_state, WORKFLOW_ISSUED)
		self.assertEqual(plan.steps[0].to_state, WORKFLOW_CLEARED)
		self.assertEqual(plan.steps[0].journal_entry, "JE-1")


class TestOpeningImportBaselineInfer(unittest.TestCase):
	def test_infer_issued_from_clear_ref_only(self):
		pdc = SimpleNamespace(
			name="X",
			is_opening_import=1,
			cheque_direction=CHEQUE_DIRECTION_PAYABLE,
			workflow_state=WORKFLOW_CLEARED,
			handover_date="2026-01-01",
		)
		with patch(
			"erpnext_extensions.cheque_management.pdc_opening_import_baseline.index_journal_references",
			return_value={
				(WORKFLOW_ISSUED, WORKFLOW_CLEARED): {"journal_entry": "JE-1"},
			},
		):
			self.assertEqual(infer_opening_import_baseline_state(pdc), WORKFLOW_ISSUED)

	def test_infer_issued_when_cleared_no_refs_but_handover(self):
		pdc = SimpleNamespace(
			name="X",
			is_opening_import=1,
			cheque_direction=CHEQUE_DIRECTION_PAYABLE,
			workflow_state=WORKFLOW_CLEARED,
			handover_date="2026-01-01",
		)
		with patch(
			"erpnext_extensions.cheque_management.pdc_opening_import_baseline.index_journal_references",
			return_value={},
		):
			self.assertEqual(infer_opening_import_baseline_state(pdc), WORKFLOW_ISSUED)


class TestOpeningImportBaselineResolve(unittest.TestCase):
	def test_stored_baseline(self):
		pdc = SimpleNamespace(
			is_opening_import=1,
			opening_import_workflow_state=WORKFLOW_SENT_TO_BANK,
			workflow_state=WORKFLOW_CLEARED,
			cheque_direction=CHEQUE_DIRECTION_RECEIVABLE,
			name="X",
		)
		self.assertEqual(resolve_opening_import_baseline_state(pdc), WORKFLOW_SENT_TO_BANK)


if __name__ == "__main__":
	unittest.main()
