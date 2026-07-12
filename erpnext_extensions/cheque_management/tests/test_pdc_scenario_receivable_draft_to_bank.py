# Copyright (c) 2025, Farbod Siyahpoosh and contributors
# For license information, please see license.txt

"""Scenario: Receivable PDC **Draft → Registered → Sent to Bank**.

Validates operational status mapping and that both workflow steps that book a **Journal Entry**
have ``journal_entry`` policy and a buildable JE payload (no live DB).

**Design note:** The full chain creates **two** JEs on the real system (register in-hand, then
move to clearing). If you expect only a single JE total, that would contradict current policy—
see :data:`_RECEIVABLE_ACCOUNTING_DECISIONS` in ``pdc_workflow_state_machine.py``.

Run from bench root::

    ./env/bin/python -m unittest erpnext_extensions.cheque_management.tests.test_pdc_scenario_receivable_draft_to_bank -v
"""

from __future__ import annotations

import io
import sys
import unittest
from datetime import date
from types import SimpleNamespace
from typing import Callable
from unittest.mock import patch

import erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque as pdc_mod
from erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque import (
	build_pdc_journal_entry_data,
	get_accounting_action,
)
from erpnext_extensions.cheque_management.pdc_workflow_state_machine import (
	CHEQUE_DIRECTION_RECEIVABLE,
	PDC_ACCOUNTING_JOURNAL_ENTRY,
	WORKFLOW_DRAFT,
	WORKFLOW_REGISTERED,
	WORKFLOW_SENT_TO_BANK,
)
from erpnext_extensions.cheque_management.pdc_workflow_to_cheque_status import (
	CHEQUE_STATUS_DRAFT,
	CHEQUE_STATUS_IN_CLEARING,
	CHEQUE_STATUS_IN_HAND,
	map_workflow_state_to_cheque_status,
)
from erpnext_extensions.cheque_management.tests.test_pdc_payload_builders import _SETTINGS_BASE, _doc

POSTING = date(2026, 4, 4)

# doc_prev, workflow_state, expect_cheque_status, step_label, expect_action | None (skip if no transition)
ChainStep = tuple[str | None, str, str, str, str | None]


def _debug_fail(message: str, checks: list[tuple[str, str]]) -> None:
	buf = io.StringIO()
	print("\n========== PDC SCENARIO DEBUG ==========", file=buf)
	print(message, file=buf)
	print("\nCheck points:", file=buf)
	for label, detail in checks:
		print(f"  • {label}: {detail}", file=buf)
	print(
		"\nWhere to look in code:",
		file=buf,
	)
	print(
		"  1. cheque_status: pdc_workflow_to_cheque_status.map_workflow_state_to_cheque_status",
		file=buf,
	)
	print(
		"  2. accounting policy: pdc_workflow_state_machine._RECEIVABLE_ACCOUNTING_DECISIONS",
		file=buf,
	)
	print(
		"  3. JE payload: post_dated_cheque.build_pdc_journal_entry_data (Registered→Sent to Bank needs clearing GL)",
		file=buf,
	)
	print(
		"  4. orchestration (live site): PostDatedCheque._pdc_pre_save_workflow_sequence / _pdc_post_save_accounting_sequence",
		file=buf,
	)
	print("========================================\n", file=buf)
	sys.stderr.write(buf.getvalue())


class TestReceivableDraftToSentToBankScenario(unittest.TestCase):
	"""Draft → Registered → Sent to Bank: status ladder + two JE legs (register + send to bank)."""

	def _run_chain_checks(
		self,
		steps: tuple[ChainStep, ...],
		extra: Callable[[], list[tuple[str, str]]] | None = None,
	) -> None:
		checks: list[tuple[str, str]] = []
		failed: str | None = None
		for doc_prev, workflow_state, expect_status, label, expect_action in steps:
			status = map_workflow_state_to_cheque_status("Receivable", workflow_state)
			checks.append((f"{label} cheque_status", f"got {status!r}, expect {expect_status!r}"))
			if status != expect_status:
				failed = f"Step {label}: cheque_status mapping failed."
				break
			if expect_action is None:
				continue
			doc = SimpleNamespace(
				cheque_direction="Receivable",
				workflow_state=workflow_state,
			)
			action = get_accounting_action(doc, doc_prev)
			checks.append((f"{label} get_accounting_action({doc_prev!r}→{workflow_state!r})", repr(action)))
			if action != expect_action:
				failed = f"Step {label}: expected accounting action {expect_action!r}, got {action!r}."
				break
		if extra:
			checks.extend(extra())
		if failed:
			_debug_fail(failed, checks)
			self.fail(failed)

	def test_scenario_final_status_in_clearing_and_accounting_is_journal_entry(self) -> None:
		steps: tuple[ChainStep, ...] = (
			# Initial Draft: no prior transition — do not assert a voucher action.
			(None, WORKFLOW_DRAFT, CHEQUE_STATUS_DRAFT, "Draft", None),
			(
				WORKFLOW_DRAFT,
				WORKFLOW_REGISTERED,
				CHEQUE_STATUS_IN_HAND,
				"Registered",
				PDC_ACCOUNTING_JOURNAL_ENTRY,
			),
			(
				WORKFLOW_REGISTERED,
				WORKFLOW_SENT_TO_BANK,
				CHEQUE_STATUS_IN_CLEARING,
				"Sent to Bank",
				PDC_ACCOUNTING_JOURNAL_ENTRY,
			),
		)
		self._run_chain_checks(steps)

	def test_scenario_registered_to_sent_bank_journal_payload_one_voucher_shape(self) -> None:
		"""Second JE leg: exactly one balanced JE payload (Dr clearing, Cr in-hand)."""
		doc = _doc()
		checks: list[tuple[str, str]] = []
		failed: str | None = None
		with (
			patch.object(pdc_mod, "_get_pdc_settings_for_company", return_value=dict(_SETTINGS_BASE)),
			patch.object(pdc_mod, "_get_party_account_or_company_default", return_value="ACC-PARTY-FALLBACK"),
			patch.object(pdc_mod, "frappe") as mf,
		):
			mf._ = lambda s: s
			je = build_pdc_journal_entry_data(doc, WORKFLOW_REGISTERED, WORKFLOW_SENT_TO_BANK, POSTING)
		checks.append(("build_pdc_journal_entry_data non-null", repr(je is not None)))
		if not je:
			failed = "Registered→Sent to Bank JE payload is None (often missing default_cheques_in_clearing_account in settings)."
		else:
			acct = je.get("accounts") or []
			checks.append(("JE accounts row count", str(len(acct))))
			if len(acct) != 2:
				failed = f"Expected 2 GL lines for send-to-bank JE, got {len(acct)}."
		if failed:
			_debug_fail(failed, checks)
			self.fail(failed)
		assert je is not None
		dr, cr = je["accounts"]
		checks.append(("Dr account (clearing)", str(dr.get("account"))))
		checks.append(("Cr account (in-hand)", str(cr.get("account"))))
		if not dr.get("debit_in_account_currency") or not cr.get("credit_in_account_currency"):
			failed = "JE lines missing debit/credit amounts."
			_debug_fail(failed, checks)
			self.fail(failed)

	def test_scenario_full_chain_two_distinct_journal_entry_transitions(self) -> None:
		"""Explicit: two policy edges are journal_entry (Draft→Registered and Registered→Sent to Bank)."""
		a1 = get_accounting_action(
			SimpleNamespace(cheque_direction=CHEQUE_DIRECTION_RECEIVABLE, workflow_state=WORKFLOW_REGISTERED),
			None,
		)
		a2 = get_accounting_action(
			SimpleNamespace(
				cheque_direction=CHEQUE_DIRECTION_RECEIVABLE, workflow_state=WORKFLOW_SENT_TO_BANK
			),
			WORKFLOW_REGISTERED,
		)
		checks = [
			("Draft→Registered action", repr(a1)),
			("Registered→Sent to Bank action", repr(a2)),
		]
		if a1 != PDC_ACCOUNTING_JOURNAL_ENTRY or a2 != PDC_ACCOUNTING_JOURNAL_ENTRY:
			_debug_fail(
				"Full chain must book two JEs (Draft→Registered and Registered→Sent to Bank).", checks
			)
			self.fail("Accounting policy mismatch for two-step chain.")
