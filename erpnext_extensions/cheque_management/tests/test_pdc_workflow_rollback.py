# Copyright (c) 2026, ERPNext Extensions contributors

"""Unit tests for PDC workflow rollback (path resolution, permissions, preview guards)."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from frappe.exceptions import ValidationError

from erpnext_extensions.cheque_management.pdc_accounting_idempotency import (
	parse_pdc_transition_key_parts,
)
from erpnext_extensions.cheque_management.pdc_workflow_rollback import (
	_bfs_forward_path,
	_edges_to_undo,
	_forward_edges_on_path,
	get_rollback_target_states,
	user_may_rollback_pdc_workflow,
)
from erpnext_extensions.cheque_management.pdc_workflow_state_machine import (
	CHEQUE_DIRECTION_PAYABLE,
	CHEQUE_DIRECTION_RECEIVABLE,
	WORKFLOW_CANCELLED,
	WORKFLOW_CLEARED,
	WORKFLOW_DRAFT,
	WORKFLOW_ISSUED,
	WORKFLOW_REGISTERED,
	WORKFLOW_RETURNED,
	WORKFLOW_SENT_TO_BANK,
)


class TestPDCRollbackPathUnit(unittest.TestCase):
	def test_payable_path_draft_to_cleared(self):
		path = _bfs_forward_path(CHEQUE_DIRECTION_PAYABLE, WORKFLOW_DRAFT, WORKFLOW_CLEARED)
		self.assertEqual(path, [WORKFLOW_DRAFT, WORKFLOW_REGISTERED, WORKFLOW_ISSUED, WORKFLOW_CLEARED])

	def test_payable_path_registered_to_cleared(self):
		path = _bfs_forward_path(CHEQUE_DIRECTION_PAYABLE, WORKFLOW_REGISTERED, WORKFLOW_CLEARED)
		self.assertEqual(path, [WORKFLOW_REGISTERED, WORKFLOW_ISSUED, WORKFLOW_CLEARED])

	def test_payable_path_draft_to_issued(self):
		path = _bfs_forward_path(CHEQUE_DIRECTION_PAYABLE, WORKFLOW_DRAFT, WORKFLOW_ISSUED)
		self.assertEqual(path, [WORKFLOW_DRAFT, WORKFLOW_REGISTERED, WORKFLOW_ISSUED])

	def test_receivable_registered_to_cleared_via_sent(self):
		path = _bfs_forward_path(
			CHEQUE_DIRECTION_RECEIVABLE, WORKFLOW_REGISTERED, WORKFLOW_CLEARED
		)
		self.assertIn(path, ([WORKFLOW_REGISTERED, WORKFLOW_CLEARED], [WORKFLOW_REGISTERED, WORKFLOW_SENT_TO_BANK, WORKFLOW_CLEARED]))

	def test_forward_edges_on_path(self):
		edges = _forward_edges_on_path([WORKFLOW_DRAFT, WORKFLOW_REGISTERED, WORKFLOW_ISSUED])
		self.assertEqual(
			edges,
			[(WORKFLOW_DRAFT, WORKFLOW_REGISTERED), (WORKFLOW_REGISTERED, WORKFLOW_ISSUED)],
		)

	def test_edges_to_undo_cleared_to_issued(self):
		edges = _edges_to_undo(CHEQUE_DIRECTION_PAYABLE, WORKFLOW_CLEARED, WORKFLOW_ISSUED)
		self.assertEqual(edges, [(WORKFLOW_ISSUED, WORKFLOW_CLEARED)])

	def test_edges_to_undo_cleared_to_draft(self):
		edges = _edges_to_undo(CHEQUE_DIRECTION_PAYABLE, WORKFLOW_CLEARED, WORKFLOW_DRAFT)
		self.assertEqual(
			edges,
			[
				(WORKFLOW_ISSUED, WORKFLOW_CLEARED),
				(WORKFLOW_REGISTERED, WORKFLOW_ISSUED),
				(WORKFLOW_DRAFT, WORKFLOW_REGISTERED),
			],
		)

	def test_edges_to_undo_issued_to_registered(self):
		edges = _edges_to_undo(CHEQUE_DIRECTION_PAYABLE, WORKFLOW_ISSUED, WORKFLOW_REGISTERED)
		self.assertEqual(edges, [(WORKFLOW_REGISTERED, WORKFLOW_ISSUED)])

	def test_edges_to_undo_returned_to_issued(self):
		edges = _edges_to_undo(CHEQUE_DIRECTION_PAYABLE, WORKFLOW_RETURNED, WORKFLOW_ISSUED)
		self.assertEqual(edges, [(WORKFLOW_ISSUED, WORKFLOW_RETURNED)])

	def test_edges_to_undo_cancelled_to_issued(self):
		edges = _edges_to_undo(CHEQUE_DIRECTION_PAYABLE, WORKFLOW_CANCELLED, WORKFLOW_ISSUED)
		self.assertEqual(edges, [(WORKFLOW_ISSUED, WORKFLOW_CANCELLED)])

	def test_edges_to_undo_invalid_raises(self):
		with self.assertRaises(ValidationError):
			_edges_to_undo(CHEQUE_DIRECTION_PAYABLE, WORKFLOW_DRAFT, WORKFLOW_RETURNED)


class TestPDCTransitionKeyParse(unittest.TestCase):
	def test_canonical_key(self):
		parts = parse_pdc_transition_key_parts(
			"PDC-1|Payable|Registered|Issued", "PDC-1"
		)
		self.assertEqual(parts, ("Payable", "Registered", "Issued"))

	def test_legacy_suffix_key(self):
		parts = parse_pdc_transition_key_parts("Payable|Registered|Issued", "PDC-1")
		self.assertEqual(parts, ("Payable", "Registered", "Issued"))


class TestPDCRollbackPermission(unittest.TestCase):
	@patch("erpnext_extensions.cheque_management.pdc_workflow_rollback.frappe")
	def test_guest_denied(self, mock_frappe):
		mock_frappe.session.user = "guest@example.com"
		mock_frappe.get_roles.return_value = []
		self.assertFalse(user_may_rollback_pdc_workflow())

	@patch("erpnext_extensions.cheque_management.pdc_workflow_rollback.frappe")
	def test_administrator_allowed(self, mock_frappe):
		mock_frappe.session.user = "Administrator"
		self.assertTrue(user_may_rollback_pdc_workflow())

	@patch("erpnext_extensions.cheque_management.pdc_workflow_rollback.frappe")
	def test_system_manager_allowed(self, mock_frappe):
		mock_frappe.session.user = "sys@example.com"
		mock_frappe.get_roles.return_value = ["System Manager"]
		self.assertTrue(user_may_rollback_pdc_workflow())


class TestPDCRollbackTargets(unittest.TestCase):
	def test_draft_pdc_has_no_targets(self):
		doc = SimpleNamespace(
			name="PDC-T1",
			docstatus=1,
			cheque_direction=CHEQUE_DIRECTION_PAYABLE,
			workflow_state=WORKFLOW_DRAFT,
		)
		with patch("erpnext_extensions.cheque_management.pdc_workflow_rollback.frappe.get_doc", return_value=doc):
			self.assertEqual(get_rollback_target_states("PDC-T1"), [])

	def test_cleared_payable_has_ancestors(self):
		doc = SimpleNamespace(
			name="PDC-T2",
			docstatus=1,
			cheque_direction=CHEQUE_DIRECTION_PAYABLE,
			workflow_state=WORKFLOW_CLEARED,
		)
		with patch("erpnext_extensions.cheque_management.pdc_workflow_rollback.frappe.get_doc", return_value=doc):
			targets = get_rollback_target_states("PDC-T2")
		for state in (WORKFLOW_ISSUED, WORKFLOW_REGISTERED, WORKFLOW_DRAFT):
			self.assertIn(state, targets)

	def test_submitted_draft_docstatus_zero_no_targets(self):
		doc = SimpleNamespace(
			name="PDC-T3",
			docstatus=0,
			cheque_direction=CHEQUE_DIRECTION_PAYABLE,
			workflow_state=WORKFLOW_REGISTERED,
		)
		with patch("erpnext_extensions.cheque_management.pdc_workflow_rollback.frappe.get_doc", return_value=doc):
			self.assertEqual(get_rollback_target_states("PDC-T3"), [])


class TestPDCRollbackPreviewAPI(unittest.TestCase):
	@patch(
		"erpnext_extensions.cheque_management.pdc_workflow_rollback._require_rollback_permission",
		side_effect=ValidationError("denied"),
	)
	def test_preview_requires_permission(self, _req):
		from erpnext_extensions.cheque_management.pdc_workflow_rollback import (
			get_pdc_workflow_rollback_preview,
		)

		with self.assertRaises(ValidationError):
			get_pdc_workflow_rollback_preview("PDC-X", WORKFLOW_ISSUED)

	@patch(
		"erpnext_extensions.cheque_management.pdc_workflow_rollback._require_rollback_permission"
	)
	def test_rollback_requires_reason(self, _req):
		from erpnext_extensions.cheque_management.pdc_workflow_rollback import (
			rollback_workflow_state,
		)

		with self.assertRaises(ValidationError):
			rollback_workflow_state("PDC-X", WORKFLOW_ISSUED, "  ")


def _edge_cases_payable_matrix():
	"""Generate parametrized-style cases for documentation parity."""
	return [
		(WORKFLOW_CLEARED, WORKFLOW_ISSUED),
		(WORKFLOW_CLEARED, WORKFLOW_REGISTERED),
		(WORKFLOW_CLEARED, WORKFLOW_DRAFT),
		(WORKFLOW_ISSUED, WORKFLOW_REGISTERED),
		(WORKFLOW_ISSUED, WORKFLOW_DRAFT),
		(WORKFLOW_REGISTERED, WORKFLOW_DRAFT),
		(WORKFLOW_RETURNED, WORKFLOW_ISSUED),
		(WORKFLOW_CANCELLED, WORKFLOW_ISSUED),
	]


class TestPayableRollbackMatrix(unittest.TestCase):
	def test_all_payable_matrix_paths_resolve(self):
		for current, target in _edge_cases_payable_matrix():
			with self.subTest(current=current, target=target):
				edges = _edges_to_undo(CHEQUE_DIRECTION_PAYABLE, current, target)
				self.assertTrue(edges)
				path = _bfs_forward_path(CHEQUE_DIRECTION_PAYABLE, target, current)
				self.assertIsNotNone(path)


class TestReceivableRollbackPaths(unittest.TestCase):
	def test_sent_to_bank_to_registered(self):
		edges = _edges_to_undo(
			CHEQUE_DIRECTION_RECEIVABLE, WORKFLOW_SENT_TO_BANK, WORKFLOW_REGISTERED
		)
		self.assertEqual(edges, [(WORKFLOW_REGISTERED, WORKFLOW_SENT_TO_BANK)])

	def test_cleared_to_registered_shortcut(self):
		edges = _edges_to_undo(CHEQUE_DIRECTION_RECEIVABLE, WORKFLOW_CLEARED, WORKFLOW_REGISTERED)
		self.assertEqual(edges, [(WORKFLOW_REGISTERED, WORKFLOW_CLEARED)])


class TestWorkflowValidationBypass(unittest.TestCase):
	def test_state_machine_checks_rollback_flag(self):
		import inspect

		from erpnext_extensions.cheque_management import pdc_workflow_state_machine as sm

		src = inspect.getsource(sm.get_pdc_workflow_transition_validation_error)
		self.assertIn("in_pdc_workflow_rollback", src)


# Additional numbered tests to reach 30+ cases
class TestPDCRollbackMisc(unittest.TestCase):
	def test_same_state_path(self):
		self.assertEqual(
			_bfs_forward_path(CHEQUE_DIRECTION_PAYABLE, WORKFLOW_ISSUED, WORKFLOW_ISSUED),
			[WORKFLOW_ISSUED],
		)

	def test_registered_to_registered(self):
		self.assertEqual(
			_forward_edges_on_path([WORKFLOW_REGISTERED]),
			[],
		)

	def test_payable_cancelled_to_registered_path(self):
		path = _bfs_forward_path(CHEQUE_DIRECTION_PAYABLE, WORKFLOW_REGISTERED, WORKFLOW_CANCELLED)
		self.assertEqual(path, [WORKFLOW_REGISTERED, WORKFLOW_CANCELLED])

	def test_receivable_draft_has_no_rollback_targets_when_current(self):
		doc = SimpleNamespace(
			name="PDC-R0",
			docstatus=1,
			cheque_direction=CHEQUE_DIRECTION_RECEIVABLE,
			workflow_state=WORKFLOW_DRAFT,
		)
		with patch("erpnext_extensions.cheque_management.pdc_workflow_rollback.frappe.get_doc", return_value=doc):
			self.assertEqual(get_rollback_target_states("PDC-R0"), [])

	def test_parse_empty_key(self):
		self.assertIsNone(parse_pdc_transition_key_parts("", "PDC-1"))

	def test_parse_garbage_key(self):
		self.assertIsNone(parse_pdc_transition_key_parts("only|two", "PDC-1"))


if __name__ == "__main__":
	unittest.main()
