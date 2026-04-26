from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.exceptions import ValidationError

import erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque as pdc_mod
from erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque import get_accounting_action
from erpnext_extensions.cheque_management.pdc_allocation import ALLOCATION_MODE_ADVANCE
from erpnext_extensions.cheque_management.pdc_workflow_state_machine import (
	CHEQUE_DIRECTION_PAYABLE,
	CHEQUE_DIRECTION_RECEIVABLE,
	WORKFLOW_ISSUED,
	WORKFLOW_REGISTERED,
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


class TestAdvanceRecognitionIssueStage(unittest.TestCase):
	def test_payable_advance_issue_stage_marks_issue_edge_as_journal_entry(self) -> None:
		doc = SimpleNamespace(
			cheque_direction=CHEQUE_DIRECTION_PAYABLE,
			workflow_state=WORKFLOW_ISSUED,
			allocation_mode=ALLOCATION_MODE_ADVANCE,
			effective_stage_for_advance_recognition="issue",
		)
		# Even though the base policy treats Registered→Issued as no_document,
		# advance-mode issue stage must override to journal_entry.
		with patch.object(pdc_mod, "get_pdc_accounting_decision", return_value="no_document"):
			act = get_accounting_action(doc, WORKFLOW_REGISTERED)
		self.assertEqual(act, "journal_entry")

	def test_receivable_advance_issue_stage_is_explicitly_blocked(self) -> None:
		doc = SimpleNamespace(
			allocation_mode=ALLOCATION_MODE_ADVANCE,
			effective_stage_for_advance_recognition="issue",
			cheque_direction=CHEQUE_DIRECTION_RECEIVABLE,
		)
		with _ThrowCtx(), self.assertRaises(ValidationError):
			pdc_mod.PostDatedCheque._validate_advance_recognition_effective_stage_supported(doc)  # type: ignore[attr-defined]

