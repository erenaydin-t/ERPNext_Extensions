"""Build PDC rollback plans from journal references + workflow path."""

from __future__ import annotations

from collections import deque
from typing import Any

import frappe
from frappe import _
from frappe.exceptions import ValidationError

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


def _edges_to_undo(
	cheque_direction: str, current: str, target: str, pdc=None
) -> list[tuple[str, str]]:
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
	je_names = [s.journal_entry for s in plan.steps if s.journal_entry]
	if not je_names:
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
	allow = linked_refs or set(je_names)
	extra = frappe.db.sql(
		"""
		SELECT name FROM `tabJournal Entry`
		WHERE docstatus = 1
		  AND name NOT IN %(known)s
		  AND (user_remark LIKE %(pat)s OR cheque_no = %(cheque_no)s)
		  AND company = %(company)s
		LIMIT 1
		""",
		{
			"known": tuple(allow) if allow else ("",),
			"pat": f"%{pdc.name}%",
			"cheque_no": (pdc.cheque_no or "")[:140],
			"company": pdc.company,
		},
		as_list=True,
	)
	if extra:
		raise ValidationError(
			_(
				"Rollback is blocked: manual or unlinked Journal Entries were found for this cheque "
				"(for example {0}). Cancel or relink them before rollback."
			).format(extra[0][0])
		)


def build_pdc_rollback_plan(pdc, target_state: str, *, reason: str = "") -> RollbackPlan:
	direction = (pdc.cheque_direction or "").strip()
	current = normalize_workflow_state_value(pdc.workflow_state)
	target = normalize_workflow_state_value(target_state)
	edge_pairs = _edges_to_undo(direction, current, target, pdc=pdc)
	steps = collect_rollback_steps_from_journal_references(pdc, edge_pairs)

	plan = RollbackPlan(
		source_doctype="Post Dated Cheque",
		source_name=pdc.name,
		current_workflow_state=current,
		target_workflow_state=target,
		reason=(reason or "").strip(),
		steps=steps,
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
