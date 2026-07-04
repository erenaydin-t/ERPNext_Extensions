# Copyright (c) 2026, ERPNext Extensions contributors
"""Controlled workflow rollback for Post Dated Cheque (Administrator / System Manager only).

Rolls ``workflow_state`` backward along valid forward paths, cancels transition Journal Entries
recorded in ``journal_references``, restores cheque leaf + instrument flags, and appends audit rows
on ``workflow_rollback_logs``.
"""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass
from typing import Any

import frappe
from frappe import _
from frappe.exceptions import ValidationError
from frappe.utils import cint, now_datetime

from erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque import (
	_pdc_get_cheque_leaf_row_for_update,
	_pdc_release_leaf_if_reserved_by_pdc,
	_pdc_reserve_leaf_for_pdc,
)
from erpnext_extensions.cheque_management.pdc_accounting_idempotency import (
	parse_pdc_transition_key_parts,
)
from erpnext_extensions.cheque_management.pdc_journal_entry_service import (
	get_existing_journal_entry_for_transition,
)
from erpnext_extensions.cheque_management.pdc_workflow_state_machine import (
	ALL_WORKFLOW_STATES,
	CHEQUE_DIRECTION_PAYABLE,
	CHEQUE_DIRECTION_RECEIVABLE,
	WORKFLOW_CANCELLED,
	WORKFLOW_CLEARED,
	WORKFLOW_DRAFT,
	WORKFLOW_ISSUED,
	WORKFLOW_REGISTERED,
	WORKFLOW_RETURNED,
	WORKFLOW_SENT_TO_BANK,
	get_workflow_transition_map,
	normalize_workflow_state_value,
)
from erpnext_extensions.cheque_management.pdc_workflow_to_cheque_status import (
	map_workflow_state_to_cheque_status,
)


@dataclass(frozen=True, slots=True)
class PDCRollbackEdge:
	from_state: str
	to_state: str
	journal_entry: str | None
	journal_reference_row: str | None
	purpose: str | None


def user_may_rollback_pdc_workflow() -> bool:
	if frappe.session.user == "Administrator":
		return True
	return "System Manager" in frappe.get_roles(frappe.session.user)


def _require_rollback_permission() -> None:
	if not user_may_rollback_pdc_workflow():
		raise ValidationError(_("Only System Manager may rollback Post Dated Cheque workflow."))


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


def get_rollback_target_states(pdc_name: str) -> list[str]:
	"""Return workflow states that are valid rollback targets for the current PDC."""
	doc = frappe.get_doc("Post Dated Cheque", pdc_name)
	direction = (doc.cheque_direction or "").strip()
	if direction not in (CHEQUE_DIRECTION_RECEIVABLE, CHEQUE_DIRECTION_PAYABLE):
		return []
	if cint(doc.docstatus) != 1:
		return []
	current = normalize_workflow_state_value(doc.workflow_state)
	if current == WORKFLOW_DRAFT:
		return []
	targets: list[str] = []
	for state in ALL_WORKFLOW_STATES:
		state = normalize_workflow_state_value(state)
		if state == current:
			continue
		if _bfs_forward_path(direction, state, current):
			targets.append(state)
	# Also allow rolling from terminal outcomes back one step when a JE proves the edge.
	if current in (WORKFLOW_CANCELLED, WORKFLOW_RETURNED):
		for cand in (WORKFLOW_ISSUED, WORKFLOW_REGISTERED):
			if _bfs_forward_path(direction, cand, current):
				targets.append(cand)
	targets = sorted(set(targets), key=lambda s: (_workflow_rank(direction, s), s))
	return targets


def _workflow_rank(direction: str, state: str) -> int:
	order_payable = [WORKFLOW_DRAFT, WORKFLOW_REGISTERED, WORKFLOW_ISSUED, WORKFLOW_CLEARED]
	order_receivable = [
		WORKFLOW_DRAFT,
		WORKFLOW_REGISTERED,
		WORKFLOW_SENT_TO_BANK,
		WORKFLOW_CLEARED,
	]
	order = order_payable if direction == CHEQUE_DIRECTION_PAYABLE else order_receivable
	state = normalize_workflow_state_value(state)
	try:
		return order.index(state)
	except ValueError:
		return 99


def _journal_rows(pdc_name: str) -> list[dict[str, Any]]:
	return frappe.get_all(
		"PDC Journal Reference",
		filters={"parent": pdc_name, "parenttype": "Post Dated Cheque"},
		fields=["name", "journal_entry", "purpose", "pdc_transition_key", "posting_date", "amount"],
		order_by="creation asc",
	)


def _edge_from_reference_row(pdc_name: str, row: dict[str, Any]) -> tuple[str, str] | None:
	key = (row.get("pdc_transition_key") or "").strip()
	if not key:
		return None
	parts = parse_pdc_transition_key_parts(key, pdc_name)
	if not parts:
		return None
	_, from_s, to_s = parts
	return from_s, to_s


def _edges_to_undo(cheque_direction: str, current: str, target: str) -> list[tuple[str, str]]:
	current = normalize_workflow_state_value(current)
	target = normalize_workflow_state_value(target)
	path = _bfs_forward_path(cheque_direction, target, current)
	if not path:
		raise ValidationError(
			_("Cannot rollback from {0} to {1}: no valid forward workflow path.").format(current, target)
		)
	return list(reversed(_forward_edges_on_path(path)))


def _collect_rollback_edges(pdc, target_state: str) -> list[PDCRollbackEdge]:
	direction = (pdc.cheque_direction or "").strip()
	current = normalize_workflow_state_value(pdc.workflow_state)
	target = normalize_workflow_state_value(target_state)
	edge_pairs = _edges_to_undo(direction, current, target)
	rows = _journal_rows(pdc.name)
	row_by_edge: dict[tuple[str, str], dict[str, Any]] = {}
	for row in rows:
		edge = _edge_from_reference_row(pdc.name, row)
		if edge:
			row_by_edge[edge] = row

	out: list[PDCRollbackEdge] = []
	for from_s, to_s in edge_pairs:
		row = row_by_edge.get((from_s, to_s))
		je = None
		if row:
			je = (row.get("journal_entry") or "").strip() or None
		else:
			je = get_existing_journal_entry_for_transition(pdc.name, direction, from_s, to_s)
		out.append(
			PDCRollbackEdge(
				from_state=from_s,
				to_state=to_s,
				journal_entry=je,
				journal_reference_row=(row.get("name") if row else None),
				purpose=(row.get("purpose") if row else None),
			)
		)
	return out


def _validate_rollback_blockers(pdc, edges: list[PDCRollbackEdge]) -> None:
	je_names = [e.journal_entry for e in edges if e.journal_entry]
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
		if frappe.db.exists(
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
		for r in _journal_rows(pdc.name)
		if (r.get("journal_entry") or "").strip()
	}
	known = {e.journal_entry for e in edges if e.journal_entry}
	allow = linked_refs or known
	if not allow:
		extra = frappe.db.sql(
			"""
			SELECT name FROM `tabJournal Entry`
			WHERE docstatus = 1
			  AND (user_remark LIKE %(pat)s OR cheque_no = %(cheque_no)s)
			  AND company = %(company)s
			LIMIT 1
			""",
			{
				"pat": f"%{pdc.name}%",
				"cheque_no": (pdc.cheque_no or "")[:140],
				"company": pdc.company,
			},
			as_list=True,
		)
	else:
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
				"known": tuple(allow),
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


def _preview_documents(edges: list[PDCRollbackEdge]) -> list[dict[str, Any]]:
	items: list[dict[str, Any]] = []
	for edge in edges:
		if not edge.journal_entry:
			continue
		items.append(
			{
				"doctype": "Journal Entry",
				"name": edge.journal_entry,
				"transition": f"{edge.from_state} → {edge.to_state}",
				"purpose": edge.purpose,
			}
		)
		for child, label in (
			("GL Entry", "GL Entries"),
			("Payment Ledger Entry", "Payment Ledger Entries"),
		):
			names = frappe.get_all(child, filters={"voucher_no": edge.journal_entry}, pluck="name", limit=5)
			if names:
				items.append(
					{
						"doctype": label,
						"names": names,
						"transition": f"{edge.from_state} → {edge.to_state}",
					}
				)
	return items


@frappe.whitelist()
def get_pdc_rollback_target_states(pdc_name: str) -> list[str]:
	_require_rollback_permission()
	return get_rollback_target_states(pdc_name)


@frappe.whitelist()
def get_pdc_workflow_rollback_preview(pdc_name: str, target_state: str) -> dict[str, Any]:
	_require_rollback_permission()
	pdc_name = (pdc_name or "").strip()
	target_state = normalize_workflow_state_value(target_state)
	if not pdc_name or not frappe.db.exists("Post Dated Cheque", pdc_name):
		raise ValidationError(_("Post Dated Cheque {0} does not exist.").format(pdc_name))

	pdc = frappe.get_doc("Post Dated Cheque", pdc_name)
	if cint(pdc.docstatus) != 1:
		raise ValidationError(_("Only submitted Post Dated Cheques can be rolled back."))

	current = normalize_workflow_state_value(pdc.workflow_state)
	allowed = get_rollback_target_states(pdc_name)
	if target_state not in allowed:
		raise ValidationError(_("Target state {0} is not allowed for rollback.").format(target_state))

	edges = _collect_rollback_edges(pdc, target_state)
	_validate_rollback_blockers(pdc, edges)
	return {
		"current_state": current,
		"target_state": target_state,
		"documents_to_remove": _preview_documents(edges),
		"transitions_to_undo": [{"from": e.from_state, "to": e.to_state} for e in edges],
	}


def _cancel_journal_entry(je_name: str) -> None:
	je = frappe.get_doc("Journal Entry", je_name)
	if je.docstatus == 1:
		je.flags.ignore_permissions = True
		je.cancel()
	elif je.docstatus == 0:
		je.flags.ignore_permissions = True
		je.delete()


def _remove_journal_reference_row(row_name: str | None) -> None:
	if row_name:
		frappe.delete_doc("PDC Journal Reference", row_name, force=1, ignore_permissions=True)


def _restore_leaf_for_target(pdc, target_state: str) -> None:
	leaf = (getattr(pdc, "cheque_leaf", None) or "").strip()
	if pdc.cheque_direction != CHEQUE_DIRECTION_PAYABLE or not leaf:
		return
	target = normalize_workflow_state_value(target_state)
	if target == WORKFLOW_DRAFT:
		row = _pdc_get_cheque_leaf_row_for_update(leaf)
		if row and row.status == "Used" and (row.linked_post_dated_cheque or "") == pdc.name:
			frappe.db.set_value(
				"Cheque Leaf",
				leaf,
				{
					"status": "Reserved",
					"linked_post_dated_cheque": None,
					"used_on": None,
					"reserved_by_pdc": pdc.name,
					"reserved_on": now_datetime(),
				},
				update_modified=False,
			)
		elif row and row.status == "Available":
			_pdc_reserve_leaf_for_pdc(leaf, pdc)
	elif target in (WORKFLOW_REGISTERED, WORKFLOW_ISSUED):
		row = _pdc_get_cheque_leaf_row_for_update(leaf)
		if row and row.status == "Reserved" and (row.reserved_by_pdc or "") == pdc.name:
			from frappe.utils import now_datetime as _now

			frappe.db.set_value(
				"Cheque Leaf",
				leaf,
				{
					"status": "Used",
					"linked_post_dated_cheque": pdc.name,
					"used_on": _now(),
					"reserved_by_pdc": None,
					"reserved_on": None,
				},
				update_modified=False,
			)


def _clear_outcome_fields_for_target(pdc, target_state: str) -> dict[str, Any]:
	target = normalize_workflow_state_value(target_state)
	updates: dict[str, Any] = {}
	if target != WORKFLOW_CLEARED:
		updates["cleared_date"] = None
		updates["clear_je_posted"] = 0
	if target in (WORKFLOW_DRAFT, WORKFLOW_REGISTERED):
		updates["returned_date"] = None
		updates["return_reason"] = None
	if target != WORKFLOW_CANCELLED:
		pass
	if target in (WORKFLOW_DRAFT, WORKFLOW_REGISTERED, WORKFLOW_ISSUED):
		updates["instrument_dead"] = 0
		updates["instrument_dead_reason"] = None
	if target in (WORKFLOW_DRAFT, WORKFLOW_REGISTERED):
		updates["recognition_je_posted"] = 0
	return updates


def _apply_workflow_state_after_rollback(pdc, target_state: str, reason: str, removed: list[dict]) -> None:
	direction = (pdc.cheque_direction or "").strip()
	target = normalize_workflow_state_value(target_state)
	cheque_status = map_workflow_state_to_cheque_status(direction, target)
	if not cheque_status:
		raise ValidationError(_("Cannot map workflow state {0} to cheque status.").format(target))

	from_state = normalize_workflow_state_value(pdc.workflow_state)
	frappe.flags.in_pdc_workflow_rollback = pdc.name
	try:
		updates = {
			"workflow_state": target,
			"cheque_status": cheque_status,
			**_clear_outcome_fields_for_target(pdc, target),
		}
		if target == WORKFLOW_DRAFT:
			updates["docstatus"] = 0

		for field, value in updates.items():
			frappe.db.set_value("Post Dated Cheque", pdc.name, field, value, update_modified=True)

		_restore_leaf_for_target(pdc, target)

		log_row = {
			"rolled_back_on": now_datetime(),
			"rolled_back_by": frappe.session.user,
			"from_state": from_state,
			"to_state": target,
			"reason": (reason or "").strip(),
			"deleted_documents": json.dumps(removed, default=str),
		}
		pdc2 = frappe.get_doc("Post Dated Cheque", pdc.name)
		pdc2.append("workflow_rollback_logs", log_row)
		pdc2.flags.ignore_validate_update_after_submit = True
		pdc2.flags.skip_pdc_accounting_orchestration = True
		pdc2.save(ignore_permissions=True)
	finally:
		frappe.flags.in_pdc_workflow_rollback = None


@frappe.whitelist()
def rollback_workflow_state(pdc_name: str, target_state: str, reason: str) -> dict[str, Any]:
	"""Rollback PDC workflow to ``target_state``; cancel transition JEs and restore instrument state."""
	_require_rollback_permission()
	reason = (reason or "").strip()
	if not reason:
		raise ValidationError(_("Rollback reason is required."))

	preview = get_pdc_workflow_rollback_preview(pdc_name, target_state)
	pdc = frappe.get_doc("Post Dated Cheque", pdc_name)
	edges = _collect_rollback_edges(pdc, preview["target_state"])
	_validate_rollback_blockers(pdc, edges)

	removed: list[dict[str, Any]] = []
	for edge in edges:
		if edge.journal_reference_row:
			_remove_journal_reference_row(edge.journal_reference_row)
		if edge.journal_entry:
			_cancel_journal_entry(edge.journal_entry)
			removed.append(
				{
					"doctype": "Journal Entry",
					"name": edge.journal_entry,
					"action": "cancelled",
					"transition": f"{edge.from_state} → {edge.to_state}",
				}
			)

	_apply_workflow_state_after_rollback(pdc, preview["target_state"], reason, removed)
	frappe.db.commit()

	return {
		"name": pdc_name,
		"workflow_state": preview["target_state"],
		"cheque_status": map_workflow_state_to_cheque_status(
			pdc.cheque_direction, preview["target_state"]
		),
		"removed_documents": removed,
	}


def sql_verify_no_orphan_gl_for_pdc(pdc_name: str, journal_entries: list[str]) -> dict[str, int]:
	"""Test helper: counts GL/PLE rows for cancelled JEs (should be 0 when docstatus=2)."""
	if not journal_entries:
		return {"gl_entry": 0, "payment_ledger_entry": 0}
	gl = frappe.db.count("GL Entry", {"voucher_no": ["in", journal_entries], "is_cancelled": 0})
	ple = frappe.db.count(
		"Payment Ledger Entry", {"voucher_no": ["in", journal_entries], "delinked": 0}
	)
	return {"gl_entry": gl, "payment_ledger_entry": ple}


def sql_verify_pdc_rollback_integrity(
	pdc_name: str,
	*,
	cancelled_journal_entries: list[str] | None = None,
) -> dict[str, int | bool]:
	"""Integration/E2E helper: verify accounting + audit tables after a rollback step."""
	cancelled_journal_entries = list(cancelled_journal_entries or [])
	out: dict[str, int | bool] = {}

	active_refs = frappe.get_all(
		"PDC Journal Reference",
		filters={"parent": pdc_name, "parenttype": "Post Dated Cheque"},
		fields=["name", "journal_entry"],
	)
	out["pdc_journal_reference"] = len(active_refs)

	for row in active_refs:
		je = row.journal_entry
		if not je or not frappe.db.exists("Journal Entry", je):
			out["orphan_journal_reference"] = True
			continue
		if frappe.db.get_value("Journal Entry", je, "docstatus") != 1:
			out["orphan_journal_reference"] = True

	out.setdefault("orphan_journal_reference", False)

	for je in cancelled_journal_entries:
		if not je:
			continue
		out[f"je_{je}_docstatus"] = frappe.db.get_value("Journal Entry", je, "docstatus") or 0
		out[f"je_{je}_gl_active"] = frappe.db.count(
			"GL Entry", {"voucher_no": je, "is_cancelled": 0}
		)
		out[f"je_{je}_ple_active"] = frappe.db.count(
			"Payment Ledger Entry", {"voucher_no": je, "delinked": 0}
		)
		out[f"je_{je}_pdc_ref"] = frappe.db.count(
			"PDC Journal Reference",
			{"parent": pdc_name, "journal_entry": je},
		)

	out["version"] = frappe.db.count(
		"Version", {"ref_doctype": "Post Dated Cheque", "docname": pdc_name}
	)
	out["comment"] = frappe.db.count(
		"Comment",
		{"reference_doctype": "Post Dated Cheque", "reference_name": pdc_name},
	)

	pdc = frappe.db.get_value(
		"Post Dated Cheque",
		pdc_name,
		["workflow_state", "cheque_status", "cheque_leaf", "cheque_direction"],
		as_dict=True,
	)
	if pdc and pdc.cheque_leaf:
		leaf = frappe.db.get_value(
			"Cheque Leaf",
			pdc.cheque_leaf,
			["status", "linked_post_dated_cheque", "reserved_by_pdc"],
			as_dict=True,
		)
		out["cheque_leaf_status"] = (leaf.status or "") if leaf else ""
		out["cheque_leaf_linked_pdc"] = (leaf.linked_post_dated_cheque or "") if leaf else ""
		out["cheque_leaf_reserved_by"] = (leaf.reserved_by_pdc or "") if leaf else ""

	# Stray GL/PLE pointing at this PDC voucher (should only exist via active submitted JEs)
	out["gl_entry_on_pdc_voucher"] = frappe.db.count(
		"GL Entry",
		{"voucher_type": "Post Dated Cheque", "voucher_no": pdc_name, "is_cancelled": 0},
	)
	out["payment_ledger_on_pdc_voucher"] = frappe.db.count(
		"Payment Ledger Entry",
		{"voucher_type": "Post Dated Cheque", "voucher_no": pdc_name, "delinked": 0},
	)

	return out


def sql_integrity_is_clean(
	report: dict[str, int | bool], cancelled_journal_entries: list[str] | None = None
) -> bool:
	if report.get("orphan_journal_reference"):
		return False
	for je in cancelled_journal_entries or []:
		if report.get(f"je_{je}_gl_active", 0):
			return False
		if report.get(f"je_{je}_ple_active", 0):
			return False
		if report.get(f"je_{je}_pdc_ref", 0):
			return False
		if report.get(f"je_{je}_docstatus") not in (None, 2):
			return False
	return True


__all__ = [
	"get_pdc_workflow_rollback_preview",
	"get_rollback_target_states",
	"rollback_workflow_state",
	"sql_integrity_is_clean",
	"sql_verify_no_orphan_gl_for_pdc",
	"sql_verify_pdc_rollback_integrity",
	"user_may_rollback_pdc_workflow",
]
