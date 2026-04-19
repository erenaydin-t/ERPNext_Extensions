# Copyright (c) 2026, Farbod Siyahpoosh and contributors
# For license information, please see license.txt

"""Orchestration-level tests: **Cleared** posts a bank-facing **Journal Entry** only.

These tests assert the final architecture:

- No Payment Entry is created for PDC lifecycle
- Clearing uses Journal Entry posting via :meth:`PostDatedCheque._pdc_post_save_accounting_sequence`

Run from bench root::

    ./env/bin/python -m unittest erpnext_extensions.cheque_management.tests.test_pdc_orchestration_journal_only_cleared -v
"""

from __future__ import annotations

import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe

import erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque as pdc_mod
import erpnext_extensions.cheque_management.pdc_journal_entry_service as je_svc
from erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque import (
	PostDatedCheque,
	build_pdc_journal_entry_data,
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

POSTING = date(2026, 10, 1)

_BANK_GL = "ACC-BANK"
_SETTINGS: dict = {
	"default_cheques_in_hand_account": "ACC-CIH",
	"default_cheques_in_clearing_account": "ACC-CLR",
	"default_payable_cheque_account": "ACC-POOL",
	"default_protested_account": "ACC-PROT",
	"default_endorsement_account": None,
}


def _doc_for_builder(direction: str) -> SimpleNamespace:
	return SimpleNamespace(
		company="_TC",
		cheque_direction=direction,
		party_type="Customer" if direction == CHEQUE_DIRECTION_RECEIVABLE else "Supplier",
		party="CUST-1" if direction == CHEQUE_DIRECTION_RECEIVABLE else "SUP-1",
		cheque_amount=1000.0,
		cheque_no="ORCH-CLR-1",
		account_paid_to="ACC-CIH",
		account_paid_from="ACC-AR-DOC",
		bank_account="BA-COMP",
		holder_party_type=None,
		holder_party=None,
	)


def _pdc_for_orchestration(direction: str, prev_state: str) -> PostDatedCheque:
	p = PostDatedCheque.__new__(PostDatedCheque)
	p.name = "PDC-ORCH-1"
	p.company = "_TC"
	p.cheque_direction = direction
	p.workflow_state = WORKFLOW_CLEARED
	p.cleared_date = POSTING
	p.bank_account = "BA-COMP"
	p.party_type = "Customer" if direction == CHEQUE_DIRECTION_RECEIVABLE else "Supplier"
	p.party = "CUST-1" if direction == CHEQUE_DIRECTION_RECEIVABLE else "SUP-1"
	p.cheque_amount = 1000.0
	p.cheque_no = "ORCH-CLR-1"
	p.flags = SimpleNamespace(skip_pdc_accounting_orchestration=False)
	p.reload = MagicMock()
	# Frappe snapshot API used by _get_previous_workflow_state_for_accounting
	p.get_value_before_save = MagicMock(return_value=prev_state)
	return p


class TestPdcClearedOrchestrationJournalOnly(unittest.TestCase):
	def test_receivable_draft_registered_sent_to_bank_cleared(self) -> None:
		"""Draft → Registered → Sent to Bank → Cleared: bank vs clearing; no PE; legacy fields remain blank."""
		doc = _doc_for_builder(CHEQUE_DIRECTION_RECEIVABLE)
		with (
			patch.object(pdc_mod, "_get_pdc_settings_for_company", return_value=dict(_SETTINGS)),
			patch.object(pdc_mod, "_get_party_account_or_company_default", return_value="ACC-AR-RES"),
			patch.object(pdc_mod, "_pdc_bank_gl_account", return_value=_BANK_GL),
			patch.object(pdc_mod, "frappe") as mf,
		):
			mf._ = lambda s: s
			j_reg = build_pdc_journal_entry_data(doc, WORKFLOW_DRAFT, WORKFLOW_REGISTERED, POSTING)
			j_stb = build_pdc_journal_entry_data(doc, WORKFLOW_REGISTERED, WORKFLOW_SENT_TO_BANK, POSTING)
			j_clr = build_pdc_journal_entry_data(doc, WORKFLOW_SENT_TO_BANK, WORKFLOW_CLEARED, POSTING)
		assert j_reg and j_stb and j_clr
		self.assertEqual(j_clr["accounts"][0]["account"], _BANK_GL)
		self.assertEqual(j_clr["accounts"][1]["account"], "ACC-CLR")

		pdc = _pdc_for_orchestration(CHEQUE_DIRECTION_RECEIVABLE, WORKFLOW_SENT_TO_BANK)
		with (
			patch.object(je_svc, "get_existing_journal_entry_for_transition", return_value=None),
			patch.object(je_svc, "post_pdc_transition_journal_entry", return_value="JE-CLR-1") as m_post,
			patch.object(frappe, "logger", return_value=SimpleNamespace(info=lambda *_a, **_k: None)),
		):
			PostDatedCheque._pdc_post_save_accounting_sequence(pdc)
		m_post.assert_called_once()

	def test_receivable_draft_registered_cleared(self) -> None:
		"""Draft → Registered → Cleared: bank vs CIH; no PE; legacy fields remain blank."""
		doc = _doc_for_builder(CHEQUE_DIRECTION_RECEIVABLE)
		with (
			patch.object(pdc_mod, "_get_pdc_settings_for_company", return_value=dict(_SETTINGS)),
			patch.object(pdc_mod, "_get_party_account_or_company_default", return_value="ACC-AR-RES"),
			patch.object(pdc_mod, "_pdc_bank_gl_account", return_value=_BANK_GL),
			patch.object(pdc_mod, "frappe") as mf,
		):
			mf._ = lambda s: s
			j_clr = build_pdc_journal_entry_data(doc, WORKFLOW_REGISTERED, WORKFLOW_CLEARED, POSTING)
		assert j_clr
		self.assertEqual(j_clr["accounts"][0]["account"], _BANK_GL)
		self.assertEqual(j_clr["accounts"][1]["account"], "ACC-CIH")

		pdc = _pdc_for_orchestration(CHEQUE_DIRECTION_RECEIVABLE, WORKFLOW_REGISTERED)
		with (
			patch.object(je_svc, "get_existing_journal_entry_for_transition", return_value=None),
			patch.object(je_svc, "post_pdc_transition_journal_entry", return_value="JE-CLR-2") as m_post,
			patch.object(frappe, "logger", return_value=SimpleNamespace(info=lambda *_a, **_k: None)),
		):
			PostDatedCheque._pdc_post_save_accounting_sequence(pdc)
		m_post.assert_called_once()

	def test_payable_draft_registered_issued_cleared(self) -> None:
		"""Draft → Registered → Issued → Cleared: pool vs bank; no party on clear; legacy fields remain blank."""
		doc = _doc_for_builder(CHEQUE_DIRECTION_PAYABLE)
		doc.account_paid_to = "ACC-AP-DOC"
		doc.account_paid_from = None
		with (
			patch.object(pdc_mod, "_get_pdc_settings_for_company", return_value=dict(_SETTINGS)),
			patch.object(pdc_mod, "_get_party_account_or_company_default", return_value="ACC-AP-RES"),
			patch.object(pdc_mod, "_pdc_bank_gl_account", return_value=_BANK_GL),
			patch.object(pdc_mod, "frappe") as mf,
		):
			mf._ = lambda s: s
			j_reg = build_pdc_journal_entry_data(doc, WORKFLOW_DRAFT, WORKFLOW_REGISTERED, POSTING)
			j_clr = build_pdc_journal_entry_data(doc, WORKFLOW_ISSUED, WORKFLOW_CLEARED, POSTING)
		assert j_reg and j_clr
		self.assertEqual(j_clr["accounts"][0]["account"], "ACC-POOL")
		self.assertEqual(j_clr["accounts"][1]["account"], _BANK_GL)
		# No party dimensions on clear
		for row in j_clr["accounts"]:
			self.assertFalse(row.get("party_type") or row.get("party"))

		pdc = _pdc_for_orchestration(CHEQUE_DIRECTION_PAYABLE, WORKFLOW_ISSUED)
		with (
			patch.object(je_svc, "get_existing_journal_entry_for_transition", return_value=None),
			patch.object(je_svc, "post_pdc_transition_journal_entry", return_value="JE-CLR-3") as m_post,
			patch.object(frappe, "logger", return_value=SimpleNamespace(info=lambda *_a, **_k: None)),
		):
			PostDatedCheque._pdc_post_save_accounting_sequence(pdc)
		m_post.assert_called_once()


if __name__ == "__main__":
	unittest.main()

