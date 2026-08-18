# Copyright (c) 2026, ERPNext Extensions contributors
"""Unit tests for event-based PDC rollback planning (v4.4.4)."""

from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from frappe.exceptions import ValidationError

from erpnext_extensions.cheque_management.accounting_rollback.models import RollbackPlan, RollbackTransitionStep
from erpnext_extensions.cheque_management.accounting_rollback.pdc.execute import operational_updates_from_steps
from erpnext_extensions.cheque_management.accounting_rollback.pdc.plan import (
	_legacy_graph_steps,
	collect_steps_from_lifecycle_events,
	event_history_rollback_targets,
	reconstruct_events_from_ordered_journal_refs,
)
from erpnext_extensions.cheque_management.accounting_rollback.transitions import get_handler
from erpnext_extensions.cheque_management.pdc_lifecycle_events import (
	EVENT_TYPE_ACCOUNTING,
	EVENT_TYPE_WORKFLOW_ONLY,
	event_type_from_accounting_action,
	parse_snapshot_json,
	snapshot_pdc_operational_fields,
)
from erpnext_extensions.cheque_management.pdc_workflow_state_machine import (
	PDC_ACCOUNTING_JOURNAL_ENTRY,
	PDC_ACCOUNTING_NO_DOCUMENT,
	WORKFLOW_DRAFT,
	WORKFLOW_ISSUED,
	WORKFLOW_REGISTERED,
	WORKFLOW_SENT_TO_BANK,
)


def _ev(seq, frm, to, event_type=EVENT_TYPE_ACCOUNTING, je=None, snapshot=None, name=None):
	return {
		"name": name or f"EV-{seq}",
		"event_sequence": seq,
		"from_state": frm,
		"to_state": to,
		"event_type": event_type,
		"purpose": "Under Collection" if to == WORKFLOW_SENT_TO_BANK else "Receive",
		"journal_entry": je,
		"journal_reference_name": f"REF-{seq}" if je else None,
		"pdc_transition_key": f"PDC-1|Receivable|{frm}|{to}",
		"snapshot_json": snapshot,
	}


def _pdc(**kw):
	base = dict(
		name="PDC-1",
		cheque_direction="Receivable",
		workflow_state=WORKFLOW_SENT_TO_BANK,
		is_opening_import=0,
	)
	base.update(kw)
	return SimpleNamespace(**base)


class TestEventTypeFromPolicy(unittest.TestCase):
	def test_journal_entry_is_accounting(self):
		self.assertEqual(event_type_from_accounting_action(PDC_ACCOUNTING_JOURNAL_ENTRY), EVENT_TYPE_ACCOUNTING)

	def test_no_document_is_workflow_only(self):
		self.assertEqual(event_type_from_accounting_action(PDC_ACCOUNTING_NO_DOCUMENT), EVENT_TYPE_WORKFLOW_ONLY)

	def test_none_is_workflow_only(self):
		self.assertEqual(event_type_from_accounting_action(None), EVENT_TYPE_WORKFLOW_ONLY)


class TestSnapshotHelpers(unittest.TestCase):
	def test_snapshot_roundtrip(self):
		doc = SimpleNamespace(
			workflow_state=WORKFLOW_REGISTERED,
			cheque_status="In Hand",
			docstatus=1,
			is_at_bank=0,
			sent_to_bank_date="2026-01-10",
			returned_from_bank_date=None,
			cleared_date=None,
			bounced_date=None,
			returned_date=None,
			return_reason=None,
			handover_date=None,
			recognition_je_posted=1,
			clear_je_posted=0,
			instrument_dead=0,
			instrument_dead_reason=None,
			holder_party="CUS-1",
			holder_party_type="Customer",
			cheque_leaf=None,
		)
		raw = snapshot_pdc_operational_fields(doc)
		parsed = parse_snapshot_json(raw)
		self.assertEqual(parsed["sent_to_bank_date"], "2026-01-10")
		self.assertEqual(parsed["is_at_bank"], 0)
		self.assertEqual(parsed["holder_party"], "CUS-1")

	def test_parse_invalid_json(self):
		self.assertEqual(parse_snapshot_json("not-json"), {})


class TestCollectStepsFromEvents(unittest.TestCase):
	def _cycle_events(self):
		return [
			_ev(1, WORKFLOW_DRAFT, WORKFLOW_REGISTERED, je="JE-R"),
			_ev(2, WORKFLOW_REGISTERED, WORKFLOW_SENT_TO_BANK, je="JE-S1"),
			_ev(3, WORKFLOW_SENT_TO_BANK, WORKFLOW_REGISTERED, je="JE-RET"),
			_ev(4, WORKFLOW_REGISTERED, WORKFLOW_SENT_TO_BANK, je="JE-S2"),
		]

	def test_latest_action_undoes_only_second_send(self):
		pdc = _pdc()
		with patch(
			"erpnext_extensions.cheque_management.accounting_rollback.pdc.plan._require_submitted_journal_entry"
		):
			steps = collect_steps_from_lifecycle_events(pdc, WORKFLOW_REGISTERED, self._cycle_events())
		self.assertEqual(len(steps), 1)
		self.assertEqual(steps[0].journal_entry, "JE-S2")
		self.assertEqual(steps[0].from_state, WORKFLOW_REGISTERED)
		self.assertEqual(steps[0].to_state, WORKFLOW_SENT_TO_BANK)

	def test_deep_rollback_to_draft_reverses_all_occurrences(self):
		pdc = _pdc()
		with patch(
			"erpnext_extensions.cheque_management.accounting_rollback.pdc.plan._require_submitted_journal_entry"
		):
			steps = collect_steps_from_lifecycle_events(pdc, WORKFLOW_DRAFT, self._cycle_events())
		jes = [s.journal_entry for s in steps]
		self.assertEqual(jes, ["JE-S2", "JE-RET", "JE-S1", "JE-R"])

	def test_repeated_send_does_not_collapse(self):
		pdc = _pdc()
		with patch(
			"erpnext_extensions.cheque_management.accounting_rollback.pdc.plan._require_submitted_journal_entry"
		):
			steps = collect_steps_from_lifecycle_events(pdc, WORKFLOW_DRAFT, self._cycle_events())
		sends = [s for s in steps if s.to_state == WORKFLOW_SENT_TO_BANK]
		self.assertEqual(len(sends), 2)

	def test_workflow_only_has_no_accounting(self):
		pdc = _pdc(cheque_direction="Payable", workflow_state=WORKFLOW_ISSUED)
		events = [
			_ev(1, WORKFLOW_DRAFT, WORKFLOW_REGISTERED, je="JE-ISSUE"),
			_ev(2, WORKFLOW_REGISTERED, WORKFLOW_ISSUED, EVENT_TYPE_WORKFLOW_ONLY, je=None),
		]
		with patch(
			"erpnext_extensions.cheque_management.accounting_rollback.pdc.plan._require_submitted_journal_entry"
		):
			steps = collect_steps_from_lifecycle_events(pdc, WORKFLOW_REGISTERED, events)
		self.assertEqual(len(steps), 1)
		self.assertEqual(steps[0].event_type, EVENT_TYPE_WORKFLOW_ONLY)
		self.assertFalse(steps[0].has_accounting)
		self.assertIsNone(steps[0].journal_entry)

	def test_mixed_history_rolls_back_accounting_then_workflow_only(self):
		pdc = _pdc(cheque_direction="Payable", workflow_state=WORKFLOW_ISSUED)
		events = [
			_ev(1, WORKFLOW_DRAFT, WORKFLOW_REGISTERED, je="JE-ISSUE"),
			_ev(2, WORKFLOW_REGISTERED, WORKFLOW_ISSUED, EVENT_TYPE_WORKFLOW_ONLY),
		]
		with patch(
			"erpnext_extensions.cheque_management.accounting_rollback.pdc.plan._require_submitted_journal_entry"
		):
			steps = collect_steps_from_lifecycle_events(pdc, WORKFLOW_DRAFT, events)
		self.assertEqual(steps[0].event_type, EVENT_TYPE_WORKFLOW_ONLY)
		self.assertEqual(steps[1].event_type, EVENT_TYPE_ACCOUNTING)
		self.assertEqual(steps[1].journal_entry, "JE-ISSUE")

	def test_missing_je_for_accounting_blocks(self):
		pdc = _pdc()
		events = [_ev(1, WORKFLOW_DRAFT, WORKFLOW_REGISTERED, je=None)]
		pdc.workflow_state = WORKFLOW_REGISTERED
		with self.assertRaises(ValidationError) as ctx:
			collect_steps_from_lifecycle_events(pdc, WORKFLOW_DRAFT, events)
		self.assertIn("no Journal Entry", str(ctx.exception))

	def test_history_mismatch_blocks(self):
		pdc = _pdc(workflow_state=WORKFLOW_REGISTERED)
		events = self._cycle_events()
		with self.assertRaises(ValidationError) as ctx:
			collect_steps_from_lifecycle_events(pdc, WORKFLOW_DRAFT, events)
		self.assertIn("lifecycle history ends", str(ctx.exception))

	def test_target_not_in_history_blocks(self):
		pdc = _pdc()
		events = [
			_ev(1, WORKFLOW_REGISTERED, WORKFLOW_SENT_TO_BANK, je="JE-S1"),
		]
		with patch(
			"erpnext_extensions.cheque_management.accounting_rollback.pdc.plan._require_submitted_journal_entry"
		):
			with self.assertRaises(ValidationError) as ctx:
				collect_steps_from_lifecycle_events(pdc, WORKFLOW_DRAFT, events)
		self.assertIn("not reachable", str(ctx.exception))


class TestEventHistoryTargets(unittest.TestCase):
	@patch(
		"erpnext_extensions.cheque_management.accounting_rollback.pdc.plan.load_active_lifecycle_events",
		return_value=[],
	)
	def test_no_events_returns_none(self, _load):
		self.assertIsNone(event_history_rollback_targets(_pdc()))

	@patch("erpnext_extensions.cheque_management.accounting_rollback.pdc.plan.load_active_lifecycle_events")
	def test_cycle_targets_include_registered_and_draft(self, load):
		load.return_value = [
			_ev(1, WORKFLOW_DRAFT, WORKFLOW_REGISTERED, je="JE-R"),
			_ev(2, WORKFLOW_REGISTERED, WORKFLOW_SENT_TO_BANK, je="JE-S1"),
			_ev(3, WORKFLOW_SENT_TO_BANK, WORKFLOW_REGISTERED, je="JE-RET"),
			_ev(4, WORKFLOW_REGISTERED, WORKFLOW_SENT_TO_BANK, je="JE-S2"),
		]
		targets = event_history_rollback_targets(_pdc())
		self.assertIn(WORKFLOW_REGISTERED, targets)
		self.assertIn(WORKFLOW_DRAFT, targets)
		self.assertNotIn(WORKFLOW_SENT_TO_BANK, targets)


class TestReconstructFromJournalRefs(unittest.TestCase):
	@patch(
		"erpnext_extensions.cheque_management.accounting_rollback.pdc.plan.ordered_journal_reference_rows"
	)
	def test_continuous_cycle_reconstructs(self, rows):
		rows.return_value = [
			{"name": "r1", "journal_entry": "JE-R", "purpose": "Receive", "pdc_transition_key": "PDC-1|Receivable|Draft|Registered"},
			{"name": "r2", "journal_entry": "JE-S1", "purpose": "Under Collection", "pdc_transition_key": "PDC-1|Receivable|Registered|Sent to Bank"},
			{"name": "r3", "journal_entry": "JE-RET", "purpose": "Return from Bank", "pdc_transition_key": "PDC-1|Receivable|Sent to Bank|Registered"},
			{"name": "r4", "journal_entry": "JE-S2", "purpose": "Under Collection", "pdc_transition_key": "PDC-1|Receivable|Registered|Sent to Bank"},
		]
		out = reconstruct_events_from_ordered_journal_refs(_pdc())
		self.assertIsNotNone(out)
		self.assertEqual(len(out), 4)
		self.assertEqual(out[-1]["journal_entry"], "JE-S2")

	@patch(
		"erpnext_extensions.cheque_management.accounting_rollback.pdc.plan.ordered_journal_reference_rows"
	)
	def test_gap_is_ambiguous(self, rows):
		rows.return_value = [
			{"name": "r1", "journal_entry": "JE-R", "purpose": "Receive", "pdc_transition_key": "PDC-1|Receivable|Draft|Registered"},
			{"name": "r2", "journal_entry": "JE-C", "purpose": "Collected", "pdc_transition_key": "PDC-1|Receivable|Sent to Bank|Cleared"},
		]
		pdc = _pdc(workflow_state="Cleared")
		self.assertIsNone(reconstruct_events_from_ordered_journal_refs(pdc))

	@patch(
		"erpnext_extensions.cheque_management.accounting_rollback.pdc.plan.journal_reference_edge_counts"
	)
	@patch(
		"erpnext_extensions.cheque_management.accounting_rollback.pdc.plan.reconstruct_events_from_ordered_journal_refs",
		return_value=None,
	)
	def test_ambiguous_cycle_legacy_blocks(self, _recon, counts):
		from collections import Counter

		counts.return_value = Counter({(WORKFLOW_REGISTERED, WORKFLOW_SENT_TO_BANK): 2})
		with self.assertRaises(ValidationError) as ctx:
			_legacy_graph_steps(_pdc(), WORKFLOW_REGISTERED)
		self.assertIn("Refusing to invent", str(ctx.exception))


class TestHandlerSelection(unittest.TestCase):
	def test_workflow_only_uses_operational_handler(self):
		step = RollbackTransitionStep(
			from_state=WORKFLOW_REGISTERED,
			to_state=WORKFLOW_ISSUED,
			event_type=EVENT_TYPE_WORKFLOW_ONLY,
			has_accounting=False,
		)
		handler = get_handler(step)
		self.assertEqual(handler.__class__.__name__, "OperationalTransitionHandler")

	def test_accounting_uses_je_handler(self):
		step = RollbackTransitionStep(
			from_state=WORKFLOW_DRAFT,
			to_state=WORKFLOW_REGISTERED,
			event_type=EVENT_TYPE_ACCOUNTING,
			journal_entry="JE-1",
			has_accounting=True,
		)
		handler = get_handler(step)
		self.assertEqual(handler.__class__.__name__, "JournalEntryTransitionHandler")


class TestOperationalRestoreFromSnapshot(unittest.TestCase):
	def test_snapshot_keeps_prior_send_date(self):
		snap = json.dumps(
			{
				"sent_to_bank_date": "2026-01-05",
				"returned_from_bank_date": "2026-01-20",
				"is_at_bank": 0,
				"cleared_date": None,
			}
		)
		plan = RollbackPlan(
			source_doctype="Post Dated Cheque",
			source_name="PDC-1",
			current_workflow_state=WORKFLOW_SENT_TO_BANK,
			target_workflow_state=WORKFLOW_REGISTERED,
			steps=[
				RollbackTransitionStep(
					from_state=WORKFLOW_REGISTERED,
					to_state=WORKFLOW_SENT_TO_BANK,
					snapshot_json=snap,
					event_type=EVENT_TYPE_ACCOUNTING,
					journal_entry="JE-S2",
				)
			],
		)
		updates = operational_updates_from_steps(_pdc(), plan)
		self.assertEqual(updates["sent_to_bank_date"], "2026-01-05")
		self.assertEqual(updates["returned_from_bank_date"], "2026-01-20")
		self.assertEqual(updates["is_at_bank"], 0)
		self.assertIsNone(updates.get("cleared_date"))

	def test_legacy_without_snapshot_uses_target_clearing(self):
		plan = RollbackPlan(
			source_doctype="Post Dated Cheque",
			source_name="PDC-1",
			current_workflow_state=WORKFLOW_SENT_TO_BANK,
			target_workflow_state=WORKFLOW_REGISTERED,
			steps=[
				RollbackTransitionStep(
					from_state=WORKFLOW_REGISTERED,
					to_state=WORKFLOW_SENT_TO_BANK,
				)
			],
		)
		updates = operational_updates_from_steps(_pdc(), plan)
		self.assertIsNone(updates.get("returned_date"))


class TestPreviousRollbackThenNewTransition(unittest.TestCase):
	def test_rolled_back_events_are_not_in_active_stack(self):
		active = [
			_ev(1, WORKFLOW_DRAFT, WORKFLOW_REGISTERED, je="JE-R"),
			_ev(3, WORKFLOW_REGISTERED, WORKFLOW_SENT_TO_BANK, je="JE-S2", name="EV-3"),
		]
		pdc = _pdc()
		with patch(
			"erpnext_extensions.cheque_management.accounting_rollback.pdc.plan._require_submitted_journal_entry"
		):
			steps = collect_steps_from_lifecycle_events(pdc, WORKFLOW_REGISTERED, active)
		self.assertEqual(len(steps), 1)
		self.assertEqual(steps[0].journal_entry, "JE-S2")


if __name__ == "__main__":
	unittest.main()
