# Copyright (c) 2026, Farbod Siyahpoosh and contributors
# For license information, please see license.txt

"""Duplicate-protection tests for PDC workflow accounting (Journal Entry idempotency).

Uses mocks (no live ERPNext posting). Run from bench::

    ./env/bin/python -m unittest erpnext_extensions.cheque_management.tests.test_pdc_accounting_duplicate_protection -v
"""

from __future__ import annotations

import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import erpnext_extensions.cheque_management.pdc_journal_entry_service as je_svc
from erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque import (
	PostDatedCheque,
)
from erpnext_extensions.cheque_management.pdc_workflow_state_machine import (
	CHEQUE_DIRECTION_RECEIVABLE,
	WORKFLOW_DRAFT,
	WORKFLOW_REGISTERED,
)


@contextmanager
def _noop_filelock(*_args, **_kwargs):
	yield


_MINIMAL_JE_PAYLOAD = {
	"voucher_type": "Journal Entry",
	"posting_date": "2026-06-01",
	"remarks": "test",
	"accounts": [
		{"account": "ACC-DR", "debit_in_account_currency": 100.0},
		{"account": "ACC-CR", "credit_in_account_currency": 100.0},
	],
}


def _pdc_mock_for_je(**overrides):
	m = SimpleNamespace(
		name="PDC-DUP-TEST",
		cheque_direction=CHEQUE_DIRECTION_RECEIVABLE,
		company="_TC",
		cheque_no="CHK-DUP",
		cheque_due_date=None,
		cheque_amount=100.0,
		meta=SimpleNamespace(name="Post Dated Cheque"),
		flags=SimpleNamespace(skip_pdc_accounting_orchestration=False),
	)
	for k, v in overrides.items():
		setattr(m, k, v)
	m.reload = MagicMock()
	m.append = MagicMock()
	m.save = MagicMock()
	return m


class TestPostPdcTransitionJournalEntryIdempotency(unittest.TestCase):
	"""Same transition: second call must not rebuild payload or invoke create/submit path."""

	def test_second_invocation_skips_build_and_create(self) -> None:
		pdc = _pdc_mock_for_je()
		with (
			patch.object(
				je_svc,
				"get_existing_journal_entry_for_transition",
				side_effect=[None, "JE-IDEM-1"],
			),
			patch.object(je_svc, "build_pdc_journal_entry_data") as m_build,
			patch.object(
				je_svc,
				"create_and_submit_journal_entry_from_payload",
				return_value="JE-IDEM-1",
			) as m_create,
		):
			m_build.return_value = dict(_MINIMAL_JE_PAYLOAD)
			r1 = je_svc.post_pdc_transition_journal_entry(pdc, WORKFLOW_DRAFT, WORKFLOW_REGISTERED)
			r2 = je_svc.post_pdc_transition_journal_entry(pdc, WORKFLOW_DRAFT, WORKFLOW_REGISTERED)
		self.assertEqual(r1, "JE-IDEM-1")
		self.assertEqual(r2, "JE-IDEM-1")
		m_build.assert_called_once()
		m_create.assert_called_once()


class TestCreateAndSubmitJournalEntryIdempotency(unittest.TestCase):
	"""Under file lock, existing transition row must return same JE without second Journal Entry doc."""

	def test_repeated_create_returns_existing_without_second_new_doc(self) -> None:
		pdc = _pdc_mock_for_je()
		je_doc = MagicMock()
		je_doc.name = "JE-FIRST"
		je_doc.append = MagicMock()

		with (
			patch.object(je_svc, "filelock", _noop_filelock),
			patch.object(
				je_svc,
				"get_existing_journal_entry_for_transition",
				side_effect=[None, "JE-FIRST"],
			),
			patch("frappe.new_doc", return_value=je_doc) as m_new_doc,
			patch("frappe._", lambda x: x),
		):
			je_doc.save = MagicMock()
			je_doc.submit = MagicMock()
			r1 = je_svc.create_and_submit_journal_entry_from_payload(
				pdc, dict(_MINIMAL_JE_PAYLOAD), WORKFLOW_DRAFT, WORKFLOW_REGISTERED
			)
			r2 = je_svc.create_and_submit_journal_entry_from_payload(
				pdc, dict(_MINIMAL_JE_PAYLOAD), WORKFLOW_DRAFT, WORKFLOW_REGISTERED
			)
		self.assertEqual(r1, "JE-FIRST")
		self.assertEqual(r2, "JE-FIRST")
		self.assertEqual(m_new_doc.call_count, 1)
		je_doc.save.assert_called_once()
		je_doc.submit.assert_called_once()
		self.assertFalse(getattr(pdc.flags, "skip_pdc_accounting_orchestration", False))


class TestPostSaveOrchestrationDuplicateProtection(unittest.TestCase):
	"""Document post-save path: no double post when JE already linked; no-op when workflow unchanged."""

	def test_existing_journal_skips_post_pdc_transition_journal_entry(self) -> None:
		class _Stub:
			name = "PDC-ORCH"
			cheque_direction = CHEQUE_DIRECTION_RECEIVABLE
			workflow_state = WORKFLOW_REGISTERED
			# Avoid frappe.getdate() → System Settings when orchestration computes posting_date.
			cleared_date = "2026-01-15"

			def __init__(self) -> None:
				self.flags = MagicMock()
				self.flags.skip_pdc_accounting_orchestration = False

			def _get_previous_workflow_state_for_accounting(self) -> str:
				return WORKFLOW_DRAFT

			def reload(self) -> None:
				pass

		stub = _Stub()
		with (
			patch("frappe.logger", return_value=MagicMock()),
			patch.object(
				je_svc,
				"get_existing_journal_entry_for_transition",
				return_value="JE-ALREADY",
			) as m_get,
			patch.object(je_svc, "post_pdc_transition_journal_entry") as m_post,
		):
			PostDatedCheque._pdc_post_save_accounting_sequence(stub)
		m_get.assert_called_once()
		m_post.assert_not_called()

	def test_same_workflow_state_skips_all_posting(self) -> None:
		class _Stub:
			name = "PDC-NOOP"
			cheque_direction = CHEQUE_DIRECTION_RECEIVABLE
			workflow_state = WORKFLOW_REGISTERED
			cleared_date = None

			def __init__(self) -> None:
				self.flags = MagicMock()
				self.flags.skip_pdc_accounting_orchestration = False

			def _get_previous_workflow_state_for_accounting(self) -> str:
				return WORKFLOW_REGISTERED

			def reload(self) -> None:
				pass

		stub = _Stub()
		with (
			patch.object(je_svc, "get_existing_journal_entry_for_transition") as m_get,
			patch.object(je_svc, "post_pdc_transition_journal_entry") as m_post,
		):
			PostDatedCheque._pdc_post_save_accounting_sequence(stub)
		m_get.assert_not_called()
		m_post.assert_not_called()


if __name__ == "__main__":
	unittest.main()
