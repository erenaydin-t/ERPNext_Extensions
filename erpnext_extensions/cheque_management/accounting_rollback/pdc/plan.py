"""Build PDC rollback plans from lifecycle events (preferred) or legacy JE/graph path."""

from __future__ import annotations

from collections import Counter, deque
from typing import Any

import frappe
from frappe import _
from frappe.exceptions import ValidationError
from frappe.utils import cint

from erpnext_extensions.cheque_management.accounting_rollback.models import (
	RollbackPlan,
	RollbackTransitionStep,
)
from erpnext_extensions.cheque_management.pdc_accounting_idempotency import (
	build_pdc_accounting_transition_key,
	parse_pdc_transition_key_parts,
)
from erpnext_extensions.cheque_management.pdc_journal_entry_service import (
	get_existing_journal_entry_for_transition,
)
from erpnext_extensions.cheque_management.pdc_lifecycle_events import (
	EVENT_TYPE_ACCOUNTING,
	EVENT_TYPE_WORKFLOW_ONLY,
	load_active_lifecycle_events,
)
from erpnext_extensions.cheque_management.pdc_workflow_state_machine import (
	CHEQUE_DIRECTION_PAYABLE,
	CHEQUE_DIRECTION_RECEIVABLE,
	WORKFLOW_DRAFT,
	WORKFLOW_ISSUED,
	WORKFLOW_REGISTERED,
	get_workflow_transition_map,
	normalize_workflow_state_value,
)
from erpnext_extensions.cheque_management.pdc_workflow_to_cheque_status import (
	map_workflow_state_to_cheque_status,
)


def _bfs_forward_path(cheque_direction: str, start: str, end: str) -> list[str] | None:
	start = normalize_workflow_state_value(start)
	end = normalize_workflow_state_value(end)
	if start == end:
		return [start]
	tm = get_workflow_transition_map(cheque_direction)
	queue: deque[tuple[str, list[str]]] = deque([(start, [start])])
	while queue:
		node, path = queue.popleft()
		for nxt in sorted(tm.get(node, ())):
			if nxt in path:
				continue
			path2 = path + [nxt]
			if nxt == end:
				return path2
			queue.append((nxt, path2))
	return None


def _forward_edges_on_path(path: list[str]) -> list[tuple[str, str]]:
	out: list[tuple[str, str]] = []
	for i in range(len(path) - 1):
		out.append((path[i], path[i + 1]))
	return out


def _edges_to_undo(cheque_direction: str, current: str, target: str, pdc=None) -> list[tuple[str, str]]:
	current = normalize_workflow_state_value(current)
	target = normalize_workflow_state_value(target)
	path = _bfs_forward_path(cheque_direction, target, current)
	if not path:
		raise ValidationError(
			_("Cannot rollback from {0} to {1}: no valid forward workflow path.").format(current, target)
		)
	edges = list(reversed(_forward_edges_on_path(path)))
	if pdc and frappe.utils.cint(getattr(pdc, "is_opening_import", 0)):
		from erpnext_extensions.cheque_management.pdc_opening_import_baseline import (
			resolve_opening_import_baseline_state,
		)

		baseline = resolve_opening_import_baseline_state(pdc)
		if baseline:
			edges = _filter_edges_at_or_after_baseline(cheque_direction, edges, baseline)
	return edges


def _filter_edges_at_or_after_baseline(
	cheque_direction: str, edges: list[tuple[str, str]], baseline: str
) -> list[tuple[str, str]]:
	from erpnext_extensions.cheque_management.pdc_opening_import_baseline import _workflow_rank

	baseline = normalize_workflow_state_value(baseline)
	out: list[tuple[str, str]] = []
	for from_s, to_s in edges:
		if _workflow_rank(cheque_direction, from_s) >= _workflow_rank(cheque_direction, baseline):
			out.append((from_s, to_s))
	return out


def index_journal_references(pdc_name: str) -> dict[tuple[str, str], dict[str, Any]]:
	rows = frappe.get_all(
		"PDC Journal Reference",
		filters={"parent": pdc_name, "parenttype": "Post Dated Cheque"},
		fields=["name", "journal_entry", "purpose", "pdc_transition_key", "posting_date", "amount"],
		order_by="creation asc",
	)
	out: dict[tuple[str, str], dict[str, Any]] = {}
	for row in rows:
		key = (row.get("pdc_transition_key") or "").strip()
		parts = parse_pdc_transition_key_parts(key, pdc_name)
		if not parts:
			continue
		_, from_s, to_s = parts
		out[(from_s, to_s)] = row
	return out


def ordered_journal_reference_rows(pdc_name: str) -> list[dict[str, Any]]:
	return frappe.get_all(
		"PDC Journal Reference",
		filters={"parent": pdc_name, "parenttype": "Post Dated Cheque"},
		fields=["name", "journal_entry", "purpose", "pdc_transition_key", "posting_date", "amount", "idx"],
		order_by="idx asc, creation asc",
	)


def journal_reference_edge_counts(pdc_name: str) -> Counter[tuple[str, str]]:
	counts: Counter[tuple[str, str]] = Counter()
	for row in ordered_journal_reference_rows(pdc_name):
		parts = parse_pdc_transition_key_parts(row.get("pdc_transition_key"), pdc_name)
		if not parts:
			continue
		_, from_s, to_s = parts
		counts[(from_s, to_s)] += 1
	return counts


def reconstruct_events_from_ordered_journal_refs(pdc) -> list[dict[str, Any]] | None:
	"""In-memory reconstruction from JE refs. Returns None when history is not a continuous chain.

	Does not persist guessed workflow-only hops. Used only when repeated (from,to) edges exist.
	"""
	current = normalize_workflow_state_value(pdc.workflow_state)
	events: list[dict[str, Any]] = []
	for row in ordered_journal_reference_rows(pdc.name):
		parts = parse_pdc_transition_key_parts(row.get("pdc_transition_key"), pdc.name)
		if not parts:
			continue
		_, from_s, to_s = parts
		events.append(
			{
				"name": None,
				"event_sequence": len(events) + 1,
				"from_state": from_s,
				"to_state": to_s,
				"event_type": EVENT_TYPE_ACCOUNTING,
				"purpose": row.get("purpose"),
				"journal_entry": row.get("journal_entry"),
				"journal_reference_name": row.get("name"),
				"pdc_transition_key": row.get("pdc_transition_key"),
				"snapshot_json": None,
			}
		)
	if not events:
		return []
	for i in range(1, len(events)):
		if normalize_workflow_state_value(events[i]["from_state"]) != normalize_workflow_state_value(
			events[i - 1]["to_state"]
		):
			return None
	if normalize_workflow_state_value(events[-1]["to_state"]) != current:
		return None
	return events


def step_from_edge(
	pdc,
	from_s: str,
	to_s: str,
	row: dict[str, Any] | None,
) -> RollbackTransitionStep:
	direction = (pdc.cheque_direction or "").strip()
	je = (row.get("journal_entry") or "").strip() if row else None
	if not je:
		je = get_existing_journal_entry_for_transition(pdc.name, direction, from_s, to_s)
	tkey = build_pdc_accounting_transition_key(pdc.name, direction, from_s, to_s)
	if row and row.get("pdc_transition_key"):
		tkey = row.get("pdc_transition_key")
	return RollbackTransitionStep(
		from_state=from_s,
		to_state=to_s,
		transition_key=tkey,
		journal_entry=je,
		journal_reference_row=(row.get("name") if row else None),
		purpose=(row.get("purpose") if row else None),
		has_accounting=bool(je),
		event_type=EVENT_TYPE_ACCOUNTING if je else EVENT_TYPE_WORKFLOW_ONLY,
	)


def collect_rollback_steps_from_journal_references(
	pdc, edge_pairs: list[tuple[str, str]]
) -> list[RollbackTransitionStep]:
	"""Authoritative undo list: workflow path order, journal reference metadata per edge."""
	row_by_edge = index_journal_references(pdc.name)
	steps: list[RollbackTransitionStep] = []
	for from_s, to_s in edge_pairs:
		row = row_by_edge.get((from_s, to_s))
		steps.append(step_from_edge(pdc, from_s, to_s, row))
	return steps


def _require_submitted_journal_entry(je: str, from_s: str, to_s: str) -> None:
	if not je:
		raise ValidationError(
			_(
				"Rollback is blocked: accounting lifecycle event {0} → {1} has no Journal Entry."
			).format(from_s, to_s)
		)
	if not frappe.db.exists("Journal Entry", je):
		raise ValidationError(
			_(
				"Rollback is blocked: Journal Entry {0} for {1} → {2} does not exist."
			).format(je, from_s, to_s)
		)
	if cint(frappe.db.get_value("Journal Entry", je, "docstatus")) != 1:
		raise ValidationError(
			_(
				"Rollback is blocked: Journal Entry {0} for {1} → {2} is not submitted."
			).format(je, from_s, to_s)
		)


def collect_steps_from_lifecycle_events(
	pdc,
	target_state: str,
	events: list[dict[str, Any]],
) -> list[RollbackTransitionStep]:
	"""Walk active events newest-first until reconstructed state equals target."""
	current = normalize_workflow_state_value(pdc.workflow_state)
	target = normalize_workflow_state_value(target_state)
	if not events:
		raise ValidationError(_("Cannot rollback: lifecycle history is empty."))

	last_to = normalize_workflow_state_value(events[-1].get("to_state"))
	if last_to != current:
		raise ValidationError(
			_(
				"Rollback is blocked: lifecycle history ends at {0} but the cheque is in {1}."
			).format(last_to, current)
		)

	direction = (pdc.cheque_direction or "").strip()
	steps: list[RollbackTransitionStep] = []
	reconstructed = current
	for ev in reversed(events):
		if reconstructed == target:
			break
		ev_to = normalize_workflow_state_value(ev.get("to_state"))
		ev_from = normalize_workflow_state_value(ev.get("from_state"))
		if ev_to != reconstructed:
			raise ValidationError(
				_(
					"Rollback is blocked: lifecycle history is not a continuous chain "
					"(expected to-state {0}, found {1})."
				).format(reconstructed, ev_to)
			)
		event_type = (ev.get("event_type") or "").strip() or EVENT_TYPE_WORKFLOW_ONLY
		je = (ev.get("journal_entry") or "").strip() or None
		if event_type == EVENT_TYPE_ACCOUNTING:
			_require_submitted_journal_entry(je or "", ev_from, ev_to)
		tkey = ev.get("pdc_transition_key") or build_pdc_accounting_transition_key(
			pdc.name, direction, ev_from, ev_to
		)
		steps.append(
			RollbackTransitionStep(
				from_state=ev_from,
				to_state=ev_to,
				transition_key=tkey,
				journal_entry=je,
				journal_reference_row=ev.get("journal_reference_name"),
				purpose=ev.get("purpose"),
				has_accounting=event_type == EVENT_TYPE_ACCOUNTING,
				event_type=event_type,
				lifecycle_event_name=ev.get("name"),
				event_sequence=ev.get("event_sequence"),
				snapshot_json=ev.get("snapshot_json"),
			)
		)
		reconstructed = ev_from

	if reconstructed != target:
		raise ValidationError(
			_(
				"Cannot rollback from {0} to {1}: target is not reachable from recorded lifecycle events."
			).format(current, target)
		)

	if frappe.utils.cint(getattr(pdc, "is_opening_import", 0)):
		from erpnext_extensions.cheque_management.pdc_opening_import_baseline import (
			_workflow_rank,
			resolve_opening_import_baseline_state,
		)

		baseline = resolve_opening_import_baseline_state(pdc)
		if baseline:
			baseline = normalize_workflow_state_value(baseline)
			filtered: list[RollbackTransitionStep] = []
			for step in steps:
				if _workflow_rank(direction, step.from_state) >= _workflow_rank(direction, baseline):
					filtered.append(step)
			steps = filtered
			if normalize_workflow_state_value(pdc.workflow_state) != target:
				# After filtering, reconstructed from remaining steps must still land on target.
				land = current
				for step in steps:
					land = step.from_state
				if land != target and target != baseline:
					raise ValidationError(
						_(
							"Cannot rollback opening-import cheque from {0} to {1}: "
							"target is below the import baseline {2}."
						).format(current, target, baseline)
					)
	return steps


def event_history_rollback_targets(pdc) -> list[str] | None:
	"""Return rollback targets from active events, or None to use the legacy graph."""
	events = load_active_lifecycle_events(pdc.name)
	if not events:
		return None
	current = normalize_workflow_state_value(pdc.workflow_state)
	last_to = normalize_workflow_state_value(events[-1].get("to_state"))
	if last_to != current:
		return []
	targets: list[str] = []
	reconstructed = current
	direction = (pdc.cheque_direction or "").strip()
	from erpnext_extensions.cheque_management.pdc_opening_import_baseline import (
		_workflow_rank,
		resolve_opening_import_baseline_state,
	)

	baseline = None
	if cint(getattr(pdc, "is_opening_import", 0)):
		baseline = resolve_opening_import_baseline_state(pdc)

	for ev in reversed(events):
		reconstructed = normalize_workflow_state_value(ev.get("from_state"))
		if reconstructed == current:
			continue
		if baseline and _workflow_rank(direction, reconstructed) < _workflow_rank(
			direction, normalize_workflow_state_value(baseline)
		):
			break
		targets.append(reconstructed)
	# Unique while preserving first-seen (latest occurrence) then sort like the legacy UI.
	unique: list[str] = []
	seen: set[str] = set()
	for state in targets:
		if state in seen:
			continue
		seen.add(state)
		unique.append(state)
	from erpnext_extensions.cheque_management.pdc_opening_import_baseline import _workflow_rank

	unique.sort(key=lambda s: (_workflow_rank(direction, s), s))
	return unique


def workflow_and_leaf_preview(pdc, target_state: str) -> tuple[dict[str, Any], dict[str, Any]]:
	target = normalize_workflow_state_value(target_state)
	direction = (pdc.cheque_direction or "").strip()
	wf = {
		"from_workflow_state": normalize_workflow_state_value(pdc.workflow_state),
		"to_workflow_state": target,
		"from_cheque_status": pdc.cheque_status,
		"to_cheque_status": map_workflow_state_to_cheque_status(direction, target),
		"docstatus_before": pdc.docstatus,
		"docstatus_after": 0 if target == WORKFLOW_DRAFT else pdc.docstatus,
	}
	leaf = {"cheque_leaf": (getattr(pdc, "cheque_leaf", None) or "").strip() or None}
	if direction == CHEQUE_DIRECTION_PAYABLE and leaf["cheque_leaf"]:
		row = frappe.db.get_value(
			"Cheque Leaf",
			leaf["cheque_leaf"],
			["status", "linked_post_dated_cheque", "reserved_by_pdc"],
			as_dict=True,
		)
		if row:
			leaf["current_status"] = row.status
			leaf["current_linked_pdc"] = row.linked_post_dated_cheque
			leaf["current_reserved_by_pdc"] = row.reserved_by_pdc
		if target == WORKFLOW_DRAFT:
			leaf["expected_status"] = "Reserved"
		elif target in (WORKFLOW_REGISTERED, WORKFLOW_ISSUED):
			leaf["expected_status"] = "Used"
	return wf, leaf


def validate_rollback_blockers(pdc, plan: RollbackPlan) -> None:
	"""Hard blockers + classified unlinked JE candidates (opening-import aware).

	Discovery of related Journal Entries does **not** itself imply BLOCK. Candidates are
	classified in :mod:`accounting_rollback.pdc.blockers` (fail closed when uncertain).
	"""
	from erpnext_extensions.cheque_management.accounting_rollback.pdc.blockers import (
		validate_unlinked_journal_entry_candidates,
	)

	je_names = [s.journal_entry for s in plan.steps if s.journal_entry]
	# Still run linked-document checks and candidate classification when the plan undoes
	# accounting, or when the PDC is an opening import (historical JEs may exist).
	is_opening = frappe.utils.cint(getattr(pdc, "is_opening_import", 0))
	if not je_names and not is_opening:
		return

	if frappe.db.count(
		"PDC Invoice Application",
		{"post_dated_cheque": pdc.name, "docstatus": 1},
	):
		raise ValidationError(
			_("Rollback is blocked: submitted PDC Invoice Applications exist for this cheque.")
		)

	for je in je_names:
		if frappe.db.table_exists("Payment Reconciliation Allocation") and frappe.db.exists(
			"Payment Reconciliation Allocation",
			{"journal_entry": je},
		):
			raise ValidationError(
				_("Rollback is blocked: Journal Entry {0} is linked to Payment Reconciliation.").format(je)
			)
		if frappe.db.exists("Bank Transaction", {"reference_name": je, "docstatus": ["!=", 2]}):
			raise ValidationError(
				_("Rollback is blocked: Journal Entry {0} is linked to Bank Reconciliation.").format(je)
			)

	linked_refs = {
		(r.get("journal_entry") or "").strip()
		for r in frappe.get_all(
			"PDC Journal Reference",
			filters={"parent": pdc.name, "parenttype": "Post Dated Cheque"},
			fields=["journal_entry"],
		)
		if (r.get("journal_entry") or "").strip()
	}
	known = set(je_names) | linked_refs
	ignored = validate_unlinked_journal_entry_candidates(pdc, plan, known)
	if ignored:
		plan.ignored_historical_journal_entries = list(ignored)


def _legacy_graph_steps(pdc, target_state: str) -> tuple[list[RollbackTransitionStep], str]:
	direction = (pdc.cheque_direction or "").strip()
	current = normalize_workflow_state_value(pdc.workflow_state)
	target = normalize_workflow_state_value(target_state)
	counts = journal_reference_edge_counts(pdc.name)
	has_cycle = any(n > 1 for n in counts.values())
	if has_cycle:
		reconstructed = reconstruct_events_from_ordered_journal_refs(pdc)
		if reconstructed is None:
			raise ValidationError(
				_(
					"Rollback is blocked: this cheque has repeated lifecycle transitions and "
					"the Journal Reference history is not a continuous unambiguous chain. "
					"Refusing to invent rollback history."
				)
			)
		if not reconstructed:
			raise ValidationError(
				_(
					"Rollback is blocked: repeated lifecycle transitions were detected but "
					"no reconstructable Journal Reference chain exists."
				)
			)
		return collect_steps_from_lifecycle_events(pdc, target, reconstructed), "reconstructed_journal_refs"

	edge_pairs = _edges_to_undo(direction, current, target, pdc=pdc)
	return collect_rollback_steps_from_journal_references(pdc, edge_pairs), "legacy_graph"


def build_pdc_rollback_plan(pdc, target_state: str, *, reason: str = "") -> RollbackPlan:
	current = normalize_workflow_state_value(pdc.workflow_state)
	target = normalize_workflow_state_value(target_state)
	events = load_active_lifecycle_events(pdc.name)
	if events:
		steps = collect_steps_from_lifecycle_events(pdc, target, events)
		history_source = "lifecycle_events"
	else:
		steps, history_source = _legacy_graph_steps(pdc, target)

	plan = RollbackPlan(
		source_doctype="Post Dated Cheque",
		source_name=pdc.name,
		current_workflow_state=current,
		target_workflow_state=target,
		reason=(reason or "").strip(),
		steps=steps,
		history_source=history_source,
	)
	if frappe.utils.cint(getattr(pdc, "is_opening_import", 0)):
		from erpnext_extensions.cheque_management.pdc_opening_import_baseline import (
			opening_import_baseline_notice,
			resolve_opening_import_baseline_state,
		)

		baseline = resolve_opening_import_baseline_state(pdc)
		plan.opening_import_baseline = baseline
		if baseline:
			plan.opening_import_notice = opening_import_baseline_notice(baseline)
	plan.workflow_changes, plan.leaf_changes = workflow_and_leaf_preview(pdc, target)
	validate_rollback_blockers(pdc, plan)
	return plan
