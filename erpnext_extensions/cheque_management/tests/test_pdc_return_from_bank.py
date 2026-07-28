# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

"""Unit tests for Return from Bank (Sent to Bank → Registered) workflow and idempotency."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from frappe.exceptions import ValidationError

import erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque as pdc_mod
from erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque import PostDatedCheque
from erpnext_extensions.cheque_management.pdc_accounting_idempotency import (
	find_open_occurrence_journal_entry,
	is_cycleable_open_occurrence_edge,
)
from erpnext_extensions.cheque_management.pdc_journal_entry_service import _purpose_for_transition
from erpnext_extensions.cheque_management.pdc_workflow_state_machine import (
	CHEQUE_DIRECTION_PAYABLE,
	CHEQUE_DIRECTION_RECEIVABLE,
	PDC_ACCOUNTING_JOURNAL_ENTRY,
	RECEIVABLE_WORKFLOW_TRANSITIONS,
	WORKFLOW_BOUNCED,
	WORKFLOW_CLEARED,
	WORKFLOW_DRAFT,
	WORKFLOW_REGISTERED,
	WORKFLOW_SENT_TO_BANK,
	get_pdc_accounting_decision,
	is_workflow_transition_allowed,
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
		"workflow_state": WORKFLOW_SENT_TO_BANK,
		"cheque_status": "In Clearing",
		"received_date": "2026-01-01",
		"cleared_date": None,
		"sent_to_bank_date": "2026-02-01",
		"returned_from_bank_date": None,
		"handover_date": None,
		"bounced_date": None,
		"returned_date": None,
		"bank_account": "BA-1",
		"cheque_amount": 1000.0,
		"cheque_no": "CHK-RFB",
		"account_paid_to": "ACC-CIH",
	}
	base.update(overrides)
	for k, v in base.items():
		setattr(p, k, v)
	return p


class TestReturnFromBankWorkflow(unittest.TestCase):
	def test_sent_to_bank_allows_registered(self):
		self.assertIn(WORKFLOW_REGISTERED, RECEIVABLE_WORKFLOW_TRANSITIONS[WORKFLOW_SENT_TO_BANK])
		self.assertTrue(
			is_workflow_transition_allowed(
				CHEQUE_DIRECTION_RECEIVABLE, WORKFLOW_SENT_TO_BANK, WORKFLOW_REGISTERED
			)
		)

	def test_return_from_bank_is_journal_entry(self):
		self.assertEqual(
			get_pdc_accounting_decision(
				CHEQUE_DIRECTION_RECEIVABLE, WORKFLOW_SENT_TO_BANK, WORKFLOW_REGISTERED
			),
			PDC_ACCOUNTING_JOURNAL_ENTRY,
		)

	def test_purpose_is_return_from_bank(self):
		self.assertEqual(
			_purpose_for_transition(
				CHEQUE_DIRECTION_RECEIVABLE, WORKFLOW_SENT_TO_BANK, WORKFLOW_REGISTERED
			),
			"Return from Bank",
		)

	def test_invalid_sources_blocked(self):
		self.assertFalse(
			is_workflow_transition_allowed(
				CHEQUE_DIRECTION_RECEIVABLE, WORKFLOW_CLEARED, WORKFLOW_REGISTERED
			)
		)
		self.assertFalse(
			is_workflow_transition_allowed(
				CHEQUE_DIRECTION_RECEIVABLE, WORKFLOW_BOUNCED, WORKFLOW_REGISTERED
			)
		)
		# Return from Bank is not an outgoing edge from Registered (only from Sent to Bank).
		self.assertNotIn(WORKFLOW_REGISTERED, RECEIVABLE_WORKFLOW_TRANSITIONS[WORKFLOW_REGISTERED])

	def test_payable_unaffected(self):
		from erpnext_extensions.cheque_management.pdc_workflow_state_machine import (
			PAYABLE_WORKFLOW_TRANSITIONS,
		)

		self.assertNotIn(WORKFLOW_SENT_TO_BANK, PAYABLE_WORKFLOW_TRANSITIONS)


class TestReturnFromBankDates(unittest.TestCase):
	def test_future_returned_from_bank_date_rejected(self):
		from datetime import date

		p = _pdc(returned_from_bank_date=date(2099, 1, 1))

		def _getdate(x=None):
			if isinstance(x, date):
				return x
			return date.fromisoformat(str(x)[:10])

		with (
			patch.object(pdc_mod, "frappe", _fake_frappe()),
			patch("frappe.utils.nowdate", return_value="2026-07-28"),
			patch("frappe.utils.getdate", side_effect=_getdate),
			self.assertRaises(ValidationError),
		):
			p._validate_important_dates_not_in_future()

	def test_re_send_requires_sent_on_or_after_returned_from_bank(self):
		from datetime import date

		p = _pdc(
			workflow_state=WORKFLOW_SENT_TO_BANK,
			sent_to_bank_date=date(2026, 1, 15),
			returned_from_bank_date=date(2026, 2, 1),
			received_date=date(2026, 1, 1),
		)
		with (
			patch.object(pdc_mod, "frappe", _fake_frappe()),
			patch.object(pdc_mod, "getdate", side_effect=lambda x=None: x),
			self.assertRaises(ValidationError),
		):
			p._validate_receivable_sent_to_bank_vs_received_date()


class TestOpenOccurrenceIdempotency(unittest.TestCase):
	def test_cycleable_edges(self):
		self.assertTrue(is_cycleable_open_occurrence_edge(WORKFLOW_REGISTERED, WORKFLOW_SENT_TO_BANK))
		self.assertTrue(is_cycleable_open_occurrence_edge(WORKFLOW_SENT_TO_BANK, WORKFLOW_REGISTERED))
		self.assertFalse(is_cycleable_open_occurrence_edge(WORKFLOW_DRAFT, WORKFLOW_REGISTERED))
		self.assertFalse(is_cycleable_open_occurrence_edge(WORKFLOW_SENT_TO_BANK, WORKFLOW_CLEARED))

	def test_open_occurrence_reuses_until_opposite(self):
		rows = [
			{
				"journal_entry": "JE-SEND-1",
				"pdc_transition_key": "PDC-1|Receivable|Registered|Sent to Bank",
				"idx": 1,
			},
			{
				"journal_entry": "JE-RET-1",
				"pdc_transition_key": "PDC-1|Receivable|Sent to Bank|Registered",
				"idx": 2,
			},
			{
				"journal_entry": "JE-SEND-2",
				"pdc_transition_key": "PDC-1|Receivable|Registered|Sent to Bank",
				"idx": 3,
			},
		]
		with patch(
			"erpnext_extensions.cheque_management.pdc_accounting_idempotency.frappe"
		) as mf:
			mf.get_all.return_value = rows
			# After send1 only — reopen with first row only
			mf.get_all.return_value = rows[:1]
			self.assertEqual(
				find_open_occurrence_journal_entry(
					"PDC-1", CHEQUE_DIRECTION_RECEIVABLE, WORKFLOW_REGISTERED, WORKFLOW_SENT_TO_BANK
				),
				"JE-SEND-1",
			)
			# After return — send closed
			mf.get_all.return_value = rows[:2]
			self.assertIsNone(
				find_open_occurrence_journal_entry(
					"PDC-1", CHEQUE_DIRECTION_RECEIVABLE, WORKFLOW_REGISTERED, WORKFLOW_SENT_TO_BANK
				)
			)
			# Return still open
			self.assertEqual(
				find_open_occurrence_journal_entry(
					"PDC-1", CHEQUE_DIRECTION_RECEIVABLE, WORKFLOW_SENT_TO_BANK, WORKFLOW_REGISTERED
				),
				"JE-RET-1",
			)
			# After send2 — send open again
			mf.get_all.return_value = rows
			self.assertEqual(
				find_open_occurrence_journal_entry(
					"PDC-1", CHEQUE_DIRECTION_RECEIVABLE, WORKFLOW_REGISTERED, WORKFLOW_SENT_TO_BANK
				),
				"JE-SEND-2",
			)
			# Return closed by send2
			self.assertIsNone(
				find_open_occurrence_journal_entry(
					"PDC-1", CHEQUE_DIRECTION_RECEIVABLE, WORKFLOW_SENT_TO_BANK, WORKFLOW_REGISTERED
				)
			)

	def test_return_without_prior_send_je_is_open_none(self):
		"""Opening-balance: no refs yet → Return posts a new JE (None = not a duplicate)."""
		with patch(
			"erpnext_extensions.cheque_management.pdc_accounting_idempotency.frappe"
		) as mf:
			mf.get_all.return_value = []
			self.assertIsNone(
				find_open_occurrence_journal_entry(
					"PDC-OB", CHEQUE_DIRECTION_RECEIVABLE, WORKFLOW_SENT_TO_BANK, WORKFLOW_REGISTERED
				)
			)


if __name__ == "__main__":
	unittest.main()
