# Copyright (c) 2026, Farbod Siyahpoosh and contributors
# For license information, please see license.txt

"""Unit tests for PDC accounting transition keys (no database)."""

from __future__ import annotations

import unittest

from unittest.mock import MagicMock, patch

from erpnext_extensions.cheque_management.pdc_accounting_idempotency import (
	build_pdc_accounting_transition_key,
	build_pdc_transition_key_suffix,
	normalize_cheque_direction_for_accounting_key,
	stored_transition_key_matches,
)
from erpnext_extensions.cheque_management.pdc_workflow_state_machine import (
	CHEQUE_DIRECTION_PAYABLE,
	CHEQUE_DIRECTION_RECEIVABLE,
	WORKFLOW_CLEARED,
	WORKFLOW_DRAFT,
	WORKFLOW_ISSUED,
	WORKFLOW_REGISTERED,
)


class TestPDCAccountingIdempotency(unittest.TestCase):
	def test_normalize_cheque_direction(self) -> None:
		self.assertEqual(
			normalize_cheque_direction_for_accounting_key("  Receivable "),
			CHEQUE_DIRECTION_RECEIVABLE,
		)
		self.assertEqual(
			normalize_cheque_direction_for_accounting_key("payable"),
			CHEQUE_DIRECTION_PAYABLE,
		)
		self.assertEqual(
			normalize_cheque_direction_for_accounting_key(None),
			CHEQUE_DIRECTION_RECEIVABLE,
		)

	def test_full_key_format(self) -> None:
		full = build_pdc_accounting_transition_key(
			"PDC-2026-001",
			CHEQUE_DIRECTION_RECEIVABLE,
			WORKFLOW_DRAFT,
			WORKFLOW_REGISTERED,
		)
		self.assertEqual(full, "PDC-2026-001|Receivable|Draft|Registered")

	def test_full_key_normalizes_direction_in_suffix(self) -> None:
		full = build_pdc_accounting_transition_key(
			"PDC-X",
			" receivable ",
			WORKFLOW_DRAFT,
			WORKFLOW_REGISTERED,
		)
		self.assertEqual(full, "PDC-X|Receivable|Draft|Registered")

	def test_suffix_matches_legacy_journal_service_alias(self) -> None:
		suffix = build_pdc_transition_key_suffix(
			CHEQUE_DIRECTION_PAYABLE,
			WORKFLOW_ISSUED,
			WORKFLOW_CLEARED,
		)
		self.assertEqual(suffix, "Payable|Issued|Cleared")

	def test_stored_matches_full_and_legacy(self) -> None:
		name = "PDC-X"
		full = build_pdc_accounting_transition_key(
			name, CHEQUE_DIRECTION_RECEIVABLE, WORKFLOW_REGISTERED, WORKFLOW_CLEARED
		)
		legacy = build_pdc_transition_key_suffix(
			CHEQUE_DIRECTION_RECEIVABLE, WORKFLOW_REGISTERED, WORKFLOW_CLEARED
		)
		self.assertTrue(
			stored_transition_key_matches(full, name, CHEQUE_DIRECTION_RECEIVABLE, WORKFLOW_REGISTERED, WORKFLOW_CLEARED)
		)
		self.assertTrue(
			stored_transition_key_matches(legacy, name, CHEQUE_DIRECTION_RECEIVABLE, WORKFLOW_REGISTERED, WORKFLOW_CLEARED)
		)
		self.assertFalse(
			stored_transition_key_matches(
				"Other|Receivable|Registered|Cleared",
				name,
				CHEQUE_DIRECTION_RECEIVABLE,
				WORKFLOW_REGISTERED,
				WORKFLOW_CLEARED,
			)
		)


class TestGetExistingJournalEntryLookup(unittest.TestCase):
	def test_exact_hit_skips_child_scan(self) -> None:
		import erpnext_extensions.cheque_management.pdc_journal_entry_service as je_svc

		with patch.object(je_svc, "frappe") as mf:
			mf.db.get_value.return_value = "JE-FAST"
			mf.get_all = MagicMock()
			found = je_svc.get_existing_journal_entry_for_transition(
				"PDC-1", CHEQUE_DIRECTION_RECEIVABLE, WORKFLOW_DRAFT, WORKFLOW_REGISTERED
			)
		self.assertEqual(found, "JE-FAST")
		mf.get_all.assert_not_called()

	def test_scans_journal_references_when_exact_misses(self) -> None:
		import erpnext_extensions.cheque_management.pdc_journal_entry_service as je_svc

		with patch.object(je_svc, "frappe") as mf:
			mf.db.get_value.return_value = None
			mf.get_all.return_value = [
				{
					"journal_entry": "JE-SCAN",
					"pdc_transition_key": f"{CHEQUE_DIRECTION_RECEIVABLE}|{WORKFLOW_DRAFT}|{WORKFLOW_REGISTERED}",
				},
			]
			found = je_svc.get_existing_journal_entry_for_transition(
				"PDC-ABB", CHEQUE_DIRECTION_RECEIVABLE, WORKFLOW_DRAFT, WORKFLOW_REGISTERED
			)
		self.assertEqual(found, "JE-SCAN")

	def test_scans_match_full_canonical_key(self) -> None:
		import erpnext_extensions.cheque_management.pdc_journal_entry_service as je_svc

		name = "PDC-FULL"
		full = build_pdc_accounting_transition_key(
			name, CHEQUE_DIRECTION_PAYABLE, WORKFLOW_ISSUED, WORKFLOW_CLEARED
		)
		with patch.object(je_svc, "frappe") as mf:
			mf.db.get_value.return_value = None
			mf.get_all.return_value = [
				{"journal_entry": "JE-CANON", "pdc_transition_key": full},
			]
			found = je_svc.get_existing_journal_entry_for_transition(
				name, CHEQUE_DIRECTION_PAYABLE, WORKFLOW_ISSUED, WORKFLOW_CLEARED
			)
		self.assertEqual(found, "JE-CANON")


if __name__ == "__main__":
	unittest.main()
