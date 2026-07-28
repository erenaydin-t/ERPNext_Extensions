# Copyright (c) 2025, Farbod Siyahpoosh and contributors
# For license information, please see license.txt

"""Unit tests for PDC accounting action selection (`get_pdc_accounting_decision` / receivable helper).

Mirrors the contract of :func:`get_accounting_action` in ``post_dated_cheque.py`` for primitive
state pairs: undefined policy → ``no_document`` after normalization.
"""

from __future__ import annotations

import unittest
from typing import Final

from erpnext_extensions.cheque_management.pdc_workflow_state_machine import (
	CHEQUE_DIRECTION_PAYABLE,
	CHEQUE_DIRECTION_RECEIVABLE,
	PAYABLE_WORKFLOW_TRANSITIONS,
	PDC_ACCOUNTING_JOURNAL_ENTRY,
	PDC_ACCOUNTING_NO_DOCUMENT,
	RECEIVABLE_WORKFLOW_TRANSITIONS,
	WORKFLOW_ASSIGNED_DEBT_PURCHASE,
	WORKFLOW_BOUNCED,
	WORKFLOW_CANCELLED,
	WORKFLOW_CLEARED,
	WORKFLOW_DEBT_PURCHASE_SETTLED,
	WORKFLOW_DRAFT,
	WORKFLOW_ENDORSED,
	WORKFLOW_ISSUED,
	WORKFLOW_REGISTERED,
	WORKFLOW_REPLACED,
	WORKFLOW_RETURNED,
	WORKFLOW_SENT_TO_BANK,
	WORKFLOW_UNDER_LEGAL_ACTION,
	get_pdc_accounting_decision,
	get_receivable_accounting_decision,
	normalize_workflow_state_value,
)

_ACCOUNTING_OUTPUTS: Final[frozenset[str]] = frozenset(
	{
		PDC_ACCOUNTING_JOURNAL_ENTRY,
		PDC_ACCOUNTING_NO_DOCUMENT,
	},
)


def _transition_edges(table: dict[str, frozenset[str]]) -> set[tuple[str, str]]:
	return {(f, t) for f, targets in table.items() for t in targets}


def _resolved_accounting_action(
	cheque_direction: str,
	previous_workflow_state: str | None,
	current_workflow_state: str | None,
) -> str:
	"""Same definitive string as PostDatedCheque.get_accounting_action (no Document)."""
	from_state = normalize_workflow_state_value(previous_workflow_state)
	to_state = normalize_workflow_state_value(current_workflow_state)
	raw = get_pdc_accounting_decision(cheque_direction, from_state, to_state)
	return PDC_ACCOUNTING_JOURNAL_ENTRY if raw == PDC_ACCOUNTING_JOURNAL_ENTRY else PDC_ACCOUNTING_NO_DOCUMENT


# Expected ``get_pdc_accounting_decision`` for every *workflow-graph* edge.
# Keys must match RECEIVABLE_WORKFLOW_TRANSITIONS exactly.
_RECEIVABLE_DECISION_BY_EDGE: Final[dict[tuple[str, str], str | None]] = {
	(WORKFLOW_DRAFT, WORKFLOW_REGISTERED): PDC_ACCOUNTING_JOURNAL_ENTRY,
	(WORKFLOW_REGISTERED, WORKFLOW_SENT_TO_BANK): PDC_ACCOUNTING_JOURNAL_ENTRY,
	(WORKFLOW_REGISTERED, WORKFLOW_CLEARED): PDC_ACCOUNTING_JOURNAL_ENTRY,
	(WORKFLOW_REGISTERED, WORKFLOW_RETURNED): PDC_ACCOUNTING_JOURNAL_ENTRY,
	(WORKFLOW_REGISTERED, WORKFLOW_ENDORSED): PDC_ACCOUNTING_JOURNAL_ENTRY,
	(WORKFLOW_REGISTERED, WORKFLOW_REPLACED): None,
	(WORKFLOW_REGISTERED, WORKFLOW_UNDER_LEGAL_ACTION): None,
	(WORKFLOW_REGISTERED, WORKFLOW_ASSIGNED_DEBT_PURCHASE): PDC_ACCOUNTING_JOURNAL_ENTRY,
	(WORKFLOW_SENT_TO_BANK, WORKFLOW_CLEARED): PDC_ACCOUNTING_JOURNAL_ENTRY,
	(WORKFLOW_SENT_TO_BANK, WORKFLOW_BOUNCED): PDC_ACCOUNTING_JOURNAL_ENTRY,
	(WORKFLOW_SENT_TO_BANK, WORKFLOW_REGISTERED): PDC_ACCOUNTING_JOURNAL_ENTRY,
	(WORKFLOW_BOUNCED, WORKFLOW_RETURNED): PDC_ACCOUNTING_NO_DOCUMENT,
	(WORKFLOW_BOUNCED, WORKFLOW_REPLACED): PDC_ACCOUNTING_JOURNAL_ENTRY,
	(WORKFLOW_BOUNCED, WORKFLOW_UNDER_LEGAL_ACTION): PDC_ACCOUNTING_NO_DOCUMENT,
	(WORKFLOW_RETURNED, WORKFLOW_REPLACED): PDC_ACCOUNTING_JOURNAL_ENTRY,
	(WORKFLOW_UNDER_LEGAL_ACTION, WORKFLOW_CLEARED): PDC_ACCOUNTING_JOURNAL_ENTRY,
	(WORKFLOW_UNDER_LEGAL_ACTION, WORKFLOW_RETURNED): None,
	(WORKFLOW_ASSIGNED_DEBT_PURCHASE, WORKFLOW_BOUNCED): PDC_ACCOUNTING_JOURNAL_ENTRY,
}

# Decision-table rows that are NOT workflow-graph edges (Cancelled drift / Facility-only settle).
# Documented separately so Cancelled drift is visible without weakening the graph contract.
_RECEIVABLE_DECISION_TABLE_ONLY: Final[dict[tuple[str, str], str | None]] = {
	(WORKFLOW_REGISTERED, WORKFLOW_CANCELLED): PDC_ACCOUNTING_NO_DOCUMENT,
	(WORKFLOW_ASSIGNED_DEBT_PURCHASE, WORKFLOW_DEBT_PURCHASE_SETTLED): PDC_ACCOUNTING_NO_DOCUMENT,
}

_PAYABLE_DECISION_BY_EDGE: Final[dict[tuple[str, str], str]] = {
	(WORKFLOW_DRAFT, WORKFLOW_REGISTERED): PDC_ACCOUNTING_JOURNAL_ENTRY,
	(WORKFLOW_REGISTERED, WORKFLOW_ISSUED): PDC_ACCOUNTING_NO_DOCUMENT,
	(WORKFLOW_ISSUED, WORKFLOW_CLEARED): PDC_ACCOUNTING_JOURNAL_ENTRY,
	(WORKFLOW_ISSUED, WORKFLOW_RETURNED): PDC_ACCOUNTING_JOURNAL_ENTRY,
	(WORKFLOW_ISSUED, WORKFLOW_REPLACED): PDC_ACCOUNTING_JOURNAL_ENTRY,
	(WORKFLOW_RETURNED, WORKFLOW_REPLACED): PDC_ACCOUNTING_JOURNAL_ENTRY,
}

# Payable Cancelled edges remain in the accounting decision table but are absent from
# PAYABLE_WORKFLOW_TRANSITIONS (Cancelled-state drift — investigate separately).
_PAYABLE_DECISION_TABLE_ONLY: Final[dict[tuple[str, str], str]] = {
	(WORKFLOW_DRAFT, WORKFLOW_CANCELLED): PDC_ACCOUNTING_NO_DOCUMENT,
	(WORKFLOW_REGISTERED, WORKFLOW_CANCELLED): PDC_ACCOUNTING_JOURNAL_ENTRY,
	(WORKFLOW_ISSUED, WORKFLOW_CANCELLED): PDC_ACCOUNTING_JOURNAL_ENTRY,
	(WORKFLOW_RETURNED, WORKFLOW_CANCELLED): PDC_ACCOUNTING_NO_DOCUMENT,
}


class TestPDCAccountingActionSelection(unittest.TestCase):
	def test_receivable_each_allowed_edge_matches_expected_decision(self) -> None:
		edges = _transition_edges(RECEIVABLE_WORKFLOW_TRANSITIONS)
		self.assertEqual(set(_RECEIVABLE_DECISION_BY_EDGE.keys()), edges)
		for (from_state, to_state), expected in _RECEIVABLE_DECISION_BY_EDGE.items():
			with self.subTest(from_state=from_state, to_state=to_state):
				got = get_pdc_accounting_decision(
					CHEQUE_DIRECTION_RECEIVABLE,
					from_state,
					to_state,
				)
				self.assertEqual(got, expected)
				self.assertEqual(
					get_receivable_accounting_decision(from_state, to_state),
					expected,
				)

	def test_payable_each_allowed_edge_matches_expected_decision(self) -> None:
		edges = _transition_edges(PAYABLE_WORKFLOW_TRANSITIONS)
		self.assertEqual(set(_PAYABLE_DECISION_BY_EDGE.keys()), edges)
		for (from_state, to_state), expected in _PAYABLE_DECISION_BY_EDGE.items():
			with self.subTest(from_state=from_state, to_state=to_state):
				got = get_pdc_accounting_decision(CHEQUE_DIRECTION_PAYABLE, from_state, to_state)
				self.assertEqual(got, expected)

	def test_receivable_decision_table_only_edges_documented(self) -> None:
		"""Cancelled / Facility-settle decisions exist outside the workflow graph (known drift)."""
		graph = _transition_edges(RECEIVABLE_WORKFLOW_TRANSITIONS)
		for edge, expected in _RECEIVABLE_DECISION_TABLE_ONLY.items():
			with self.subTest(edge=edge):
				self.assertNotIn(edge, graph)
				self.assertEqual(
					get_pdc_accounting_decision(CHEQUE_DIRECTION_RECEIVABLE, edge[0], edge[1]),
					expected,
				)

	def test_payable_decision_table_only_cancelled_edges_documented(self) -> None:
		graph = _transition_edges(PAYABLE_WORKFLOW_TRANSITIONS)
		for edge, expected in _PAYABLE_DECISION_TABLE_ONLY.items():
			with self.subTest(edge=edge):
				self.assertNotIn(edge, graph)
				self.assertEqual(
					get_pdc_accounting_decision(CHEQUE_DIRECTION_PAYABLE, edge[0], edge[1]),
					expected,
				)

	def test_defined_decisions_are_only_journal_or_no_document(self) -> None:
		for direction, table in (
			(CHEQUE_DIRECTION_RECEIVABLE, _RECEIVABLE_DECISION_BY_EDGE),
			(CHEQUE_DIRECTION_PAYABLE, _PAYABLE_DECISION_BY_EDGE),
		):
			for (f, t), decision in table.items():
				with self.subTest(direction=direction, edge=(f, t)):
					if decision is None:
						continue
					self.assertIn(decision, _ACCOUNTING_OUTPUTS)

	def test_resolved_action_is_always_one_of_two_for_all_allowed_edges(self) -> None:
		for from_state, to_state in _transition_edges(RECEIVABLE_WORKFLOW_TRANSITIONS):
			with self.subTest(direction="Receivable", edge=(from_state, to_state)):
				out = _resolved_accounting_action(
					CHEQUE_DIRECTION_RECEIVABLE,
					from_state,
					to_state,
				)
				self.assertIn(out, _ACCOUNTING_OUTPUTS)
		for from_state, to_state in _transition_edges(PAYABLE_WORKFLOW_TRANSITIONS):
			with self.subTest(direction="Payable", edge=(from_state, to_state)):
				out = _resolved_accounting_action(
					CHEQUE_DIRECTION_PAYABLE,
					from_state,
					to_state,
				)
				self.assertIn(out, _ACCOUNTING_OUTPUTS)

	def test_unknown_cheque_direction_decision_is_none_resolved_is_no_document(self) -> None:
		self.assertIsNone(
			get_pdc_accounting_decision("", WORKFLOW_DRAFT, WORKFLOW_REGISTERED),
		)
		self.assertEqual(
			_resolved_accounting_action("", WORKFLOW_DRAFT, WORKFLOW_REGISTERED),
			PDC_ACCOUNTING_NO_DOCUMENT,
		)

	def test_whitespace_normalized_like_get_accounting_action(self) -> None:
		self.assertEqual(
			_resolved_accounting_action(
				CHEQUE_DIRECTION_RECEIVABLE,
				f"  {WORKFLOW_DRAFT}  ",
				f"  {WORKFLOW_REGISTERED}  ",
			),
			PDC_ACCOUNTING_JOURNAL_ENTRY,
		)
