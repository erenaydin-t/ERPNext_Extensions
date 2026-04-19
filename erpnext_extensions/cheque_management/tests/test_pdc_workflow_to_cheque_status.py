# Copyright (c) 2025, Farbod Siyahpoosh and contributors
# For license information, please see license.txt

"""Unit tests for :func:`map_workflow_state_to_cheque_status` and related helpers."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from erpnext_extensions.cheque_management.pdc_workflow_state_machine import (
	ALL_WORKFLOW_STATES,
	CHEQUE_DIRECTION_PAYABLE,
	CHEQUE_DIRECTION_RECEIVABLE,
	WORKFLOW_BOUNCED,
	WORKFLOW_CLEARED,
	WORKFLOW_ENDORSED,
	WORKFLOW_ISSUED,
	WORKFLOW_SENT_TO_BANK,
	WORKFLOW_UNDER_LEGAL_ACTION,
)
from erpnext_extensions.cheque_management.pdc_workflow_to_cheque_status import (
	CHEQUE_STATUS_DRAFT,
	PAYABLE_WORKFLOW_TO_CHEQUE_STATUS,
	RECEIVABLE_WORKFLOW_TO_CHEQUE_STATUS,
	get_cheque_status_for_workflow_state,
	get_cheque_status_from_workflow,
	map_workflow_state_to_cheque_status,
)


class TestPDCWorkflowToChequeStatus(unittest.TestCase):
	def test_receivable_every_mapped_workflow_state(self) -> None:
		for workflow_state, expected_cheque_status in RECEIVABLE_WORKFLOW_TO_CHEQUE_STATUS.items():
			with self.subTest(workflow_state=workflow_state):
				got = map_workflow_state_to_cheque_status(
					CHEQUE_DIRECTION_RECEIVABLE,
					workflow_state,
				)
				self.assertEqual(got, expected_cheque_status)

	def test_payable_every_mapped_workflow_state(self) -> None:
		for workflow_state, expected_cheque_status in PAYABLE_WORKFLOW_TO_CHEQUE_STATUS.items():
			with self.subTest(workflow_state=workflow_state):
				got = map_workflow_state_to_cheque_status(
					CHEQUE_DIRECTION_PAYABLE,
					workflow_state,
				)
				self.assertEqual(got, expected_cheque_status)

	def test_receivable_unmapped_workflow_states_are_none(self) -> None:
		for ws in ALL_WORKFLOW_STATES:
			if ws in RECEIVABLE_WORKFLOW_TO_CHEQUE_STATUS:
				continue
			with self.subTest(workflow_state=ws):
				self.assertIsNone(
					map_workflow_state_to_cheque_status(CHEQUE_DIRECTION_RECEIVABLE, ws),
				)

	def test_payable_unmapped_workflow_states_are_none(self) -> None:
		for ws in ALL_WORKFLOW_STATES:
			if ws in PAYABLE_WORKFLOW_TO_CHEQUE_STATUS:
				continue
			with self.subTest(workflow_state=ws):
				self.assertIsNone(
					map_workflow_state_to_cheque_status(CHEQUE_DIRECTION_PAYABLE, ws),
				)

	def test_explicit_cross_direction_gaps(self) -> None:
		# Documented: Issued has no receivable cheque_status row.
		self.assertIsNone(
			map_workflow_state_to_cheque_status(CHEQUE_DIRECTION_RECEIVABLE, WORKFLOW_ISSUED),
		)
		# Payable map omits receivable-only / clearing states.
		for ws in (
			WORKFLOW_SENT_TO_BANK,
			WORKFLOW_BOUNCED,
			WORKFLOW_ENDORSED,
			WORKFLOW_UNDER_LEGAL_ACTION,
		):
			with self.subTest(workflow_state=ws):
				self.assertIsNone(
					map_workflow_state_to_cheque_status(CHEQUE_DIRECTION_PAYABLE, ws),
				)

	def test_unknown_cheque_direction_returns_none(self) -> None:
		self.assertIsNone(map_workflow_state_to_cheque_status("", "Draft"))
		self.assertIsNone(map_workflow_state_to_cheque_status("Other", "Draft"))

	def test_blank_workflow_state_normalizes_to_draft(self) -> None:
		for direction in (CHEQUE_DIRECTION_RECEIVABLE, CHEQUE_DIRECTION_PAYABLE):
			for blank in (None, "", "  ", "\t"):
				with self.subTest(direction=direction, blank=repr(blank)):
					got = map_workflow_state_to_cheque_status(direction, blank)
					self.assertEqual(got, CHEQUE_STATUS_DRAFT)

	def test_get_cheque_status_from_workflow(self) -> None:
		doc = SimpleNamespace(
			cheque_direction=CHEQUE_DIRECTION_RECEIVABLE,
			workflow_state="Registered",
		)
		self.assertEqual(
			get_cheque_status_from_workflow(doc),
			RECEIVABLE_WORKFLOW_TO_CHEQUE_STATUS["Registered"],
		)

	def test_get_cheque_status_for_workflow_state_alias(self) -> None:
		self.assertEqual(
			get_cheque_status_for_workflow_state(CHEQUE_DIRECTION_PAYABLE, "Issued"),
			map_workflow_state_to_cheque_status(CHEQUE_DIRECTION_PAYABLE, "Issued"),
		)

	def test_workflow_state_label_trimmed_before_lookup(self) -> None:
		self.assertEqual(
			map_workflow_state_to_cheque_status(
				CHEQUE_DIRECTION_RECEIVABLE,
				f"  {WORKFLOW_CLEARED}  ",
			),
			RECEIVABLE_WORKFLOW_TO_CHEQUE_STATUS[WORKFLOW_CLEARED],
		)
