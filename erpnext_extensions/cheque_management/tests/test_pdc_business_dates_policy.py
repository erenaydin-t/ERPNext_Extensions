# Copyright (c) 2026, Farbod Siyahpoosh and contributors
# For license information, please see license.txt

"""Business date enforcement for PDC workflow checkpoints (received/cleared/sent-to-bank/returned/bounced)."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from frappe.exceptions import ValidationError

import erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque as pdc_mod
from erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque import PostDatedCheque
from erpnext_extensions.cheque_management.pdc_workflow_state_machine import (
	CHEQUE_DIRECTION_PAYABLE,
	CHEQUE_DIRECTION_RECEIVABLE,
	WORKFLOW_BOUNCED,
	WORKFLOW_CLEARED,
	WORKFLOW_DRAFT,
	WORKFLOW_ENDORSED,
	WORKFLOW_ISSUED,
	WORKFLOW_REGISTERED,
	WORKFLOW_RETURNED,
	WORKFLOW_SENT_TO_BANK,
)


def _fake_frappe():
	def _throw(msg, *args, **kwargs):
		raise ValidationError(msg if isinstance(msg, str) else str(msg))

	return SimpleNamespace(_=lambda s: s, throw=_throw)


def _pdc(**overrides) -> PostDatedCheque:
	p = PostDatedCheque.__new__(PostDatedCheque)
	p.flags = SimpleNamespace(skip_pdc_accounting_orchestration=False)
	base = {
		"company": "_TC",
		"cheque_direction": CHEQUE_DIRECTION_RECEIVABLE,
		"workflow_state": WORKFLOW_REGISTERED,
		"cheque_status": "In Hand",
		"received_date": None,
		"cleared_date": None,
		"sent_to_bank_date": None,
		"handover_date": None,
		"bounced_date": None,
		"returned_date": None,
		"return_reason": "Reason",
		"bank_account": "BA-1",
		"cheque_amount": 1000.0,
		"cheque_no": "CHK-1",
		"account_paid_to": "ACC-CIH",
	}
	base.update(overrides)
	for k, v in base.items():
		setattr(p, k, v)
	return p


class TestPdcBusinessDatesPhase1(unittest.TestCase):
	def test_receivable_register_requires_received_date(self):
		p = _pdc(cheque_direction=CHEQUE_DIRECTION_RECEIVABLE, workflow_state=WORKFLOW_REGISTERED, received_date=None)
		with (
			patch.object(p, "_get_previous_workflow_state_raw", return_value=WORKFLOW_DRAFT),
			patch.object(pdc_mod, "frappe", _fake_frappe()),
			self.assertRaises(ValidationError),
		):
			p._validate_received_date_required_for_receivable_registered()

	def test_cleared_requires_cleared_date(self):
		p = _pdc(workflow_state=WORKFLOW_CLEARED, cleared_date=None)
		with (
			patch.object(p, "_get_previous_workflow_state_for_accounting", return_value=WORKFLOW_REGISTERED),
			patch.object(pdc_mod, "frappe", _fake_frappe()),
			self.assertRaises(ValidationError),
		):
			p._validate_clearing_accounting_payload()

	def test_returned_requires_returned_date(self):
		p = _pdc(workflow_state=WORKFLOW_RETURNED, returned_date=None)
		with (
			patch.object(pdc_mod, "frappe", _fake_frappe()),
			self.assertRaises(ValidationError),
		):
			p._validate_returned_workflow_state()

	def test_payable_issued_requires_handover_date(self):
		p = _pdc(
			workflow_state=WORKFLOW_ISSUED,
			cheque_direction=CHEQUE_DIRECTION_PAYABLE,
			handover_date=None,
		)
		with (
			patch.object(pdc_mod, "frappe", _fake_frappe()),
			self.assertRaises(ValidationError),
		):
			p._validate_issued_workflow_state()

	def test_endorsed_requires_handover_date(self):
		p = _pdc(
			workflow_state=WORKFLOW_ENDORSED,
			cheque_direction=CHEQUE_DIRECTION_RECEIVABLE,
			holder_party_type="Customer",
			holder_party="C-1",
			handover_date=None,
		)
		ff = _fake_frappe()
		ff.db = SimpleNamespace(exists=lambda *a, **k: True)
		with (
			patch.object(pdc_mod, "frappe", ff),
			self.assertRaises(ValidationError),
		):
			p._validate_endorsed_workflow_state()

	def test_sent_to_bank_requires_sent_to_bank_date(self):
		p = _pdc(
			workflow_state=WORKFLOW_SENT_TO_BANK,
			cheque_direction=CHEQUE_DIRECTION_RECEIVABLE,
			sent_to_bank_date=None,
		)
		with (
			patch.object(pdc_mod, "frappe", _fake_frappe()),
			self.assertRaises(ValidationError),
		):
			p._validate_sent_to_bank_workflow_state()

	def test_bounced_requires_bounced_date(self):
		p = _pdc(
			workflow_state=WORKFLOW_BOUNCED,
			cheque_direction=CHEQUE_DIRECTION_RECEIVABLE,
			bounced_date=None,
		)
		with (
			patch.object(p, "_get_previous_workflow_state_raw", return_value=WORKFLOW_SENT_TO_BANK),
			patch.object(pdc_mod, "frappe", _fake_frappe()),
			self.assertRaises(ValidationError),
		):
			p._validate_bounced_workflow_state()

	def test_posting_date_selection_uses_received_cleared_returned(self):
		"""_pdc_post_save_accounting_sequence chooses posting_date by to_state."""
		p = _pdc(workflow_state=WORKFLOW_CLEARED, cleared_date="2026-02-01")
		p.name = "PDC-1"
		p._get_previous_workflow_state_for_accounting = lambda: WORKFLOW_SENT_TO_BANK
		p.reload = lambda: None
		with (
			patch("frappe.logger", return_value=SimpleNamespace(info=lambda *_a, **_k: None)),
			patch("erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque.get_accounting_action", return_value="journal_entry"),
			patch("erpnext_extensions.cheque_management.pdc_journal_entry_service.get_existing_journal_entry_for_transition", return_value=None),
			patch("erpnext_extensions.cheque_management.pdc_journal_entry_service.post_pdc_transition_journal_entry", return_value="JE-1") as m_post,
		):
			PostDatedCheque._pdc_post_save_accounting_sequence(p)
		kw = m_post.call_args.kwargs
		self.assertEqual(kw.get("posting_date"), "2026-02-01")

	def test_returned_posting_date_uses_only_returned_date(self):
		"""Returned transition JE must post on returned_date (not cheque_due_date / today fallback)."""
		p = _pdc(
			workflow_state=WORKFLOW_RETURNED,
			returned_date="2026-03-15",
			cheque_due_date="2026-01-01",
			received_date="2026-02-01",
			cheque_status="Returned to Customer",
		)
		p.name = "PDC-RET-1"
		p._get_previous_workflow_state_for_accounting = lambda: WORKFLOW_REGISTERED
		p.reload = lambda: None
		with (
			patch("frappe.logger", return_value=SimpleNamespace(info=lambda *_a, **_k: None)),
			patch("erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque.get_accounting_action", return_value="journal_entry"),
			patch("erpnext_extensions.cheque_management.pdc_journal_entry_service.get_existing_journal_entry_for_transition", return_value=None),
			patch("erpnext_extensions.cheque_management.pdc_journal_entry_service.post_pdc_transition_journal_entry", return_value="JE-RET-1") as m_post,
		):
			PostDatedCheque._pdc_post_save_accounting_sequence(p)
		self.assertEqual(m_post.call_args.kwargs.get("posting_date"), "2026-03-15")

	def test_bounced_posting_date_uses_only_bounced_date(self):
		"""Bounced transition JE must post on bounced_date (not due/received/today fallback)."""
		p = _pdc(
			workflow_state=WORKFLOW_BOUNCED,
			cheque_direction=CHEQUE_DIRECTION_RECEIVABLE,
			bounced_date="2026-04-20",
			cheque_due_date="2026-01-01",
			received_date="2026-02-01",
			returned_date="2026-03-01",
		)
		p.name = "PDC-BNC-1"
		p._get_previous_workflow_state_for_accounting = lambda: WORKFLOW_SENT_TO_BANK
		p.reload = lambda: None
		with (
			patch("frappe.logger", return_value=SimpleNamespace(info=lambda *_a, **_k: None)),
			patch("erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque.get_accounting_action", return_value="journal_entry"),
			patch("erpnext_extensions.cheque_management.pdc_journal_entry_service.get_existing_journal_entry_for_transition", return_value=None),
			patch("erpnext_extensions.cheque_management.pdc_journal_entry_service.post_pdc_transition_journal_entry", return_value="JE-BNC-1") as m_post,
		):
			PostDatedCheque._pdc_post_save_accounting_sequence(p)
		self.assertEqual(m_post.call_args.kwargs.get("posting_date"), "2026-04-20")

	def test_sent_to_bank_posting_date_uses_only_sent_to_bank_date(self):
		"""Sent to Bank transition JE must post on sent_to_bank_date (not received/due/today)."""
		p = _pdc(
			workflow_state=WORKFLOW_SENT_TO_BANK,
			cheque_direction=CHEQUE_DIRECTION_RECEIVABLE,
			sent_to_bank_date="2026-05-10",
			cheque_due_date="2026-01-01",
			received_date="2026-02-01",
		)
		p.name = "PDC-STB-1"
		p._get_previous_workflow_state_for_accounting = lambda: WORKFLOW_REGISTERED
		p.reload = lambda: None
		with (
			patch("frappe.logger", return_value=SimpleNamespace(info=lambda *_a, **_k: None)),
			patch("erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque.get_accounting_action", return_value="journal_entry"),
			patch("erpnext_extensions.cheque_management.pdc_journal_entry_service.get_existing_journal_entry_for_transition", return_value=None),
			patch("erpnext_extensions.cheque_management.pdc_journal_entry_service.post_pdc_transition_journal_entry", return_value="JE-STB-1") as m_post,
		):
			PostDatedCheque._pdc_post_save_accounting_sequence(p)
		self.assertEqual(m_post.call_args.kwargs.get("posting_date"), "2026-05-10")

	def test_payable_issued_posting_date_uses_handover_date(self):
		p = _pdc(
			workflow_state=WORKFLOW_ISSUED,
			cheque_direction=CHEQUE_DIRECTION_PAYABLE,
			handover_date="2026-06-01",
			received_date="2026-01-15",
			cheque_due_date="2026-12-31",
		)
		p.name = "PDC-ISS-1"
		p._get_previous_workflow_state_for_accounting = lambda: WORKFLOW_DRAFT
		p.reload = lambda: None
		with (
			patch("frappe.logger", return_value=SimpleNamespace(info=lambda *_a, **_k: None)),
			patch("erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque.get_accounting_action", return_value="journal_entry"),
			patch("erpnext_extensions.cheque_management.pdc_journal_entry_service.get_existing_journal_entry_for_transition", return_value=None),
			patch("erpnext_extensions.cheque_management.pdc_journal_entry_service.post_pdc_transition_journal_entry", return_value="JE-ISS-1") as m_post,
		):
			PostDatedCheque._pdc_post_save_accounting_sequence(p)
		self.assertEqual(m_post.call_args.kwargs.get("posting_date"), "2026-06-01")

	def test_receivable_endorsed_posting_date_uses_handover_date(self):
		p = _pdc(
			workflow_state=WORKFLOW_ENDORSED,
			cheque_direction=CHEQUE_DIRECTION_RECEIVABLE,
			handover_date="2026-06-15",
			received_date="2026-01-20",
		)
		p.name = "PDC-END-1"
		p._get_previous_workflow_state_for_accounting = lambda: WORKFLOW_REGISTERED
		p.reload = lambda: None
		with (
			patch("frappe.logger", return_value=SimpleNamespace(info=lambda *_a, **_k: None)),
			patch("erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque.get_accounting_action", return_value="journal_entry"),
			patch("erpnext_extensions.cheque_management.pdc_journal_entry_service.get_existing_journal_entry_for_transition", return_value=None),
			patch("erpnext_extensions.cheque_management.pdc_journal_entry_service.post_pdc_transition_journal_entry", return_value="JE-END-1") as m_post,
		):
			PostDatedCheque._pdc_post_save_accounting_sequence(p)
		self.assertEqual(m_post.call_args.kwargs.get("posting_date"), "2026-06-15")


if __name__ == "__main__":
	unittest.main()

