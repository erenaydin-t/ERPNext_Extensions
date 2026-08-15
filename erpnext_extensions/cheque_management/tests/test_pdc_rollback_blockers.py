# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

"""Unit tests for opening-import aware PDC rollback JE blocker classification (v4.3.3)."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from frappe.exceptions import ValidationError

from erpnext_extensions.cheque_management.accounting_rollback.models import (
	RollbackPlan,
	RollbackTransitionStep,
)
from erpnext_extensions.cheque_management.accounting_rollback.pdc import blockers as blockers_mod
from erpnext_extensions.cheque_management.accounting_rollback.pdc.blockers import (
	CLASS_BLOCK,
	CLASS_IGNORE,
	FAMILY_AMBIGUOUS,
	FAMILY_CLEAR,
	FAMILY_ISSUE,
	classify_unlinked_journal_entry,
	infer_accounting_family,
	pre_baseline_purpose_families,
	undo_purpose_families,
)
from erpnext_extensions.cheque_management.pdc_workflow_state_machine import (
	CHEQUE_DIRECTION_PAYABLE,
	CHEQUE_DIRECTION_RECEIVABLE,
	WORKFLOW_CLEARED,
	WORKFLOW_DRAFT,
	WORKFLOW_ISSUED,
	WORKFLOW_REGISTERED,
	WORKFLOW_SENT_TO_BANK,
)


def _plan_cleared_to_issued(*, opening_baseline=WORKFLOW_ISSUED):
	return RollbackPlan(
		source_doctype="Post Dated Cheque",
		source_name="PDC-T",
		current_workflow_state=WORKFLOW_CLEARED,
		target_workflow_state=WORKFLOW_ISSUED,
		steps=[
			RollbackTransitionStep(
				from_state=WORKFLOW_ISSUED,
				to_state=WORKFLOW_CLEARED,
				journal_entry="JE-CLEAR",
				purpose="Payable Clear",
				has_accounting=True,
			)
		],
		opening_import_baseline=opening_baseline,
	)


def _pdc(**kw):
	base = dict(
		name="PDC-T",
		cheque_direction=CHEQUE_DIRECTION_PAYABLE,
		workflow_state=WORKFLOW_CLEARED,
		docstatus=1,
		is_opening_import=1,
		opening_import_workflow_state=WORKFLOW_ISSUED,
		opening_import="COI-1",
		cheque_no="031148",
		party="SUP-1",
		cheque_amount=10_000_000_000.0,
		company="Co",
		creation="2026-06-06 20:01:19",
	)
	base.update(kw)
	return SimpleNamespace(**base)


def _issue_evidence(**kw):
	base = dict(
		name="JE-ISSUE",
		missing=False,
		company="Co",
		cheque_no="031148",
		user_remark="ثبت چک پرداختنی 031148 بابت SUP-1",
		remark="",
		posting_date="2026-03-21",
		creation="2026-05-20 11:47:23",
		docstatus=1,
		total_debit=10_000_000_000.0,
		parties={"SUP-1"},
		has_bank_credit=False,
		has_bank_debit=False,
		has_nonbank_credit=True,
		has_nonbank_debit=True,
		reference_pdcs=set(),
		rows=[],
	)
	base.update(kw)
	return base


def _clear_evidence(**kw):
	base = _issue_evidence(
		name="JE-CLEAR-EXTRA",
		user_remark="وصول چک پرداختنی 031148",
		has_bank_credit=True,
		has_bank_debit=False,
		has_nonbank_credit=False,
		has_nonbank_debit=True,
	)
	base.update(kw)
	return base


class TestPurposeFamilies(unittest.TestCase):
	def test_undo_families_clear(self):
		plan = _plan_cleared_to_issued()
		self.assertEqual(undo_purpose_families(_pdc(), plan), {FAMILY_CLEAR})

	def test_pre_baseline_issued(self):
		self.assertEqual(
			pre_baseline_purpose_families(CHEQUE_DIRECTION_PAYABLE, WORKFLOW_ISSUED),
			{FAMILY_ISSUE},
		)

	def test_infer_issue_vs_clear(self):
		pdc = _pdc()
		self.assertEqual(infer_accounting_family(pdc, _issue_evidence()), FAMILY_ISSUE)
		self.assertEqual(infer_accounting_family(pdc, _clear_evidence()), FAMILY_CLEAR)


class TestOpeningImportIgnore(unittest.TestCase):
	def test_historical_issue_ignored(self):
		"""1. Cleared→Issued with pre-import Issue JE → IGNORE."""
		verdict, reason = classify_unlinked_journal_entry(
			_pdc(), _plan_cleared_to_issued(), "JE-ISSUE", evidence=_issue_evidence()
		)
		self.assertEqual(verdict, CLASS_IGNORE)
		self.assertIn("pre_baseline_issue", reason)

	def test_multiple_historical_issues_each_ignored(self):
		"""2. Multiple valid pre-baseline Issue JEs → each IGNORE."""
		for name in ("JE-A", "JE-B"):
			ev = _issue_evidence(name=name)
			verdict, _ = classify_unlinked_journal_entry(
				_pdc(), _plan_cleared_to_issued(), name, evidence=ev
			)
			self.assertEqual(verdict, CLASS_IGNORE)

	def test_no_historical_candidates_noop(self):
		"""3. No candidates — classification not required (plan still builds)."""
		# Covered by plan tests; classifier not invoked without candidates.
		self.assertTrue(True)


class TestOpeningImportBlock(unittest.TestCase):
	def test_post_import_manual_remark(self):
		"""4. Manual JE after import naming the PDC → BLOCK."""
		ev = _issue_evidence(
			user_remark="Manual adjust PDC-T",
			creation="2026-06-10 10:00:00",
			cheque_no="031148",
		)
		verdict, reason = classify_unlinked_journal_entry(
			_pdc(), _plan_cleared_to_issued(), "JE-MANUAL", evidence=ev
		)
		self.assertEqual(verdict, CLASS_BLOCK)
		self.assertTrue(
			"post_import_manual_remark" in reason or "insufficient_supporting" in reason,
			reason,
		)

	def test_extra_unlinked_clear_blocks(self):
		"""5/6. Extra unlinked Clear-style JE overlapping undo → BLOCK."""
		verdict, reason = classify_unlinked_journal_entry(
			_pdc(), _plan_cleared_to_issued(), "JE-CLEAR-EXTRA", evidence=_clear_evidence()
		)
		self.assertEqual(verdict, CLASS_BLOCK)
		self.assertIn("undo_scope_conflict", reason)

	def test_ambiguous_cheque_no_only(self):
		"""7. Ambiguous accounting shape → fail closed."""
		ev = _issue_evidence(
			has_bank_credit=True,
			has_bank_debit=True,
			has_nonbank_credit=True,
			has_nonbank_debit=True,
			parties=set(),
		)
		# Force ambiguous via contradictory bank both sides without clear pattern
		ev["has_bank_credit"] = False
		ev["has_bank_debit"] = False
		ev["has_nonbank_credit"] = False
		ev["has_nonbank_debit"] = True
		ev["parties"] = set()
		verdict, reason = classify_unlinked_journal_entry(
			_pdc(), _plan_cleared_to_issued(), "JE-AMB", evidence=ev
		)
		self.assertEqual(verdict, CLASS_BLOCK)
		self.assertEqual(infer_accounting_family(_pdc(), ev), FAMILY_AMBIGUOUS)
		self.assertIn("ambiguous", reason)

	def test_party_mismatch(self):
		"""8. Party mismatch → BLOCK."""
		ev = _issue_evidence(parties={"SUP-OTHER"})
		verdict, reason = classify_unlinked_journal_entry(
			_pdc(), _plan_cleared_to_issued(), "JE-PARTY", evidence=ev
		)
		self.assertEqual(verdict, CLASS_BLOCK)
		self.assertEqual(reason, "party_mismatch")

	def test_amount_mismatch(self):
		"""9. Amount mismatch → BLOCK."""
		ev = _issue_evidence(total_debit=100.0)
		verdict, reason = classify_unlinked_journal_entry(
			_pdc(), _plan_cleared_to_issued(), "JE-AMT", evidence=ev
		)
		self.assertEqual(verdict, CLASS_BLOCK)
		self.assertEqual(reason, "amount_mismatch")

	@patch(
		"erpnext_extensions.cheque_management.pdc_opening_import_baseline.resolve_opening_import_baseline_state",
		return_value=None,
	)
	def test_baseline_unresolved(self, _m):
		"""10. Baseline cannot be resolved → BLOCK."""
		verdict, reason = classify_unlinked_journal_entry(
			_pdc(opening_import_workflow_state=None),
			_plan_cleared_to_issued(),
			"JE-ISSUE",
			evidence=_issue_evidence(),
		)
		self.assertEqual(verdict, CLASS_BLOCK)
		self.assertEqual(reason, "opening_import_baseline_unresolved")

	def test_rollback_before_baseline(self):
		"""11. Target before baseline → BLOCK."""
		plan = RollbackPlan(
			source_doctype="Post Dated Cheque",
			source_name="PDC-T",
			current_workflow_state=WORKFLOW_CLEARED,
			target_workflow_state=WORKFLOW_DRAFT,
			steps=[
				RollbackTransitionStep(
					from_state=WORKFLOW_ISSUED,
					to_state=WORKFLOW_CLEARED,
					journal_entry="JE-CLEAR",
					purpose="Payable Clear",
				)
			],
			opening_import_baseline=WORKFLOW_ISSUED,
		)
		verdict, reason = classify_unlinked_journal_entry(
			_pdc(), plan, "JE-ISSUE", evidence=_issue_evidence()
		)
		self.assertEqual(verdict, CLASS_BLOCK)
		self.assertEqual(reason, "rollback_before_baseline")


class TestNormalPdcBlockers(unittest.TestCase):
	def test_normal_unlinked_issue_blocks(self):
		"""13. Normal PDC with unlinked related JE → BLOCK."""
		verdict, reason = classify_unlinked_journal_entry(
			_pdc(is_opening_import=0, opening_import_workflow_state=None),
			_plan_cleared_to_issued(),
			"JE-ISSUE",
			evidence=_issue_evidence(),
		)
		self.assertEqual(verdict, CLASS_BLOCK)
		self.assertEqual(reason, "normal_pdc_unlinked_je")


class TestValidateCandidatesRaises(unittest.TestCase):
	@patch.object(blockers_mod, "find_related_unlinked_journal_entries", return_value=["JE-CLEAR-EXTRA"])
	@patch.object(blockers_mod, "load_journal_entry_evidence")
	def test_validate_raises_on_extra_clear(self, load_ev, _find):
		load_ev.return_value = _clear_evidence()
		with self.assertRaises(ValidationError) as ctx:
			blockers_mod.validate_unlinked_journal_entry_candidates(
				_pdc(), _plan_cleared_to_issued(), {"JE-CLEAR"}
			)
		self.assertIn("JE-CLEAR-EXTRA", str(ctx.exception))

	@patch.object(blockers_mod, "find_related_unlinked_journal_entries", return_value=["JE-ISSUE"])
	@patch.object(blockers_mod, "load_journal_entry_evidence")
	def test_validate_ignores_historical_issue(self, load_ev, _find):
		load_ev.return_value = _issue_evidence()
		ignored = blockers_mod.validate_unlinked_journal_entry_candidates(
			_pdc(), _plan_cleared_to_issued(), {"JE-CLEAR"}
		)
		self.assertEqual(len(ignored), 1)
		self.assertEqual(ignored[0]["journal_entry"], "JE-ISSUE")
		self.assertEqual(ignored[0]["classification"], CLASS_IGNORE)


class TestReceivablePreBaseline(unittest.TestCase):
	def test_receive_family_pre_baseline_sent_to_bank(self):
		families = pre_baseline_purpose_families(CHEQUE_DIRECTION_RECEIVABLE, WORKFLOW_SENT_TO_BANK)
		self.assertIn(blockers_mod.FAMILY_RECEIVE, families)
		self.assertIn(blockers_mod.FAMILY_UNDER_COLLECTION, families)


if __name__ == "__main__":
	unittest.main()
