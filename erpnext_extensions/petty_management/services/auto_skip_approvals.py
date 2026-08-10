# Copyright (c) 2026, ERPNext Extensions contributors
"""Consecutive same-user approval auto-skip (v4.1.4).

Primary identity gate: session user MUST equal the stamped approver for the
candidate stage. Role alone never authorizes auto-skip.

After an explicit Approve, while the session user is still the stamped approver
for the *next* Approve transition *and* Frappe ``get_transitions`` exposes that
Approve, automatically apply via normal ``apply_workflow``.

Never auto-applies Reject, funding, Close, or Payment Entry actions.
Never ``db_set`` workflow_state.
Each hop leaves normal Workflow Action history / Version / Timeline.
Assignment Rules are refreshed so only the real pending approver keeps an Open ToDo.
"""

from __future__ import annotations

import frappe
from frappe.model.document import Document
from frappe.model.workflow import apply_workflow as frappe_apply_workflow
from frappe.model.workflow import get_transitions

# Approve-only actions eligible for consecutive auto-skip.
PM_AUTO_SKIP_APPROVE_ACTIONS = frozenset(
	{
		"PM Manager Approve",
		"PM CEO Approve",
		"PM Finance Approve",
		"PM Approve",  # Clearance finance alias
	}
)

# Stamped User field that must match session user for each Approve action.
PM_APPROVE_STAMP_FIELD = {
	"PM Manager Approve": "manager_approver",
	"PM CEO Approve": "ceo_approver",
	"PM Finance Approve": "finance_approver",
	"PM Approve": "finance_approver",
}

_MAX_AUTO_SKIP_HOPS = 5


def stamped_approver_for_action(doc: Document, action: str) -> str | None:
	"""Return the stamped User for this Approve action, or None if unknown."""
	field = PM_APPROVE_STAMP_FIELD.get(action)
	if not field:
		return None
	return (doc.get(field) or "").strip() or None


def session_matches_stamped_approver(doc: Document, action: str) -> bool:
	"""Primary identity gate: current user == stamped approver for this exact stage."""
	stamped = stamped_approver_for_action(doc, action)
	if not stamped:
		return False
	return stamped == frappe.session.user


def _pick_auto_skip_action(doc: Document, transitions: list) -> str | None:
	"""Return one Approve action allowed by Frappe transitions AND stamp identity."""
	candidates = []
	for t in transitions or []:
		action = (t.get("action") if isinstance(t, dict) else getattr(t, "action", None)) or ""
		if action not in PM_AUTO_SKIP_APPROVE_ACTIONS:
			continue
		if not session_matches_stamped_approver(doc, action):
			continue
		candidates.append(action)
	if not candidates:
		return None
	# Prefer PM Finance Approve over alias PM Approve when both appear.
	if "PM Finance Approve" in candidates:
		return "PM Finance Approve"
	return candidates[0]


def _workflow_state_title(doc: Document) -> str:
	link = (doc.get("workflow_state") or "").strip()
	if not link:
		return ""
	return (frappe.db.get_value("Workflow State", link, "workflow_state_name") or link or "").strip()


def _expected_open_assignee(doc: Document) -> str | None:
	"""Stamped User who should hold the sole Open ToDo for the current pending state."""
	title = _workflow_state_title(doc)
	if title == "Pending Manager Approval":
		return (doc.get("manager_approver") or "").strip() or None
	if title == "Pending CEO Approval":
		return (doc.get("ceo_approver") or "").strip() or None
	if title in ("Pending Finance Approval", "Pending Finance Review"):
		return (doc.get("finance_approver") or "").strip() or None
	return None


def refresh_pm_assignment_rules(doc: Document) -> None:
	"""Close stale ToDos and create the next Assignment Rule ToDo for this doc."""
	from frappe.automation.doctype.assignment_rule.assignment_rule import apply as apply_assignment_rules

	try:
		apply_assignment_rules(doc=doc)
	except Exception:
		frappe.log_error(
			title="PM Assignment Rule refresh failed",
			message=frappe.get_traceback(),
		)


def finalize_pm_assignments_after_auto_skip(doc: Document) -> None:
	"""After the skip loop, leave at most one active assignee — the real pending approver.

	Closes Open ToDos that are not for the current pending stamped user (including
	intermediate same-user stage ToDos that would otherwise remain actionable).
	Then re-applies Assignment Rules so the next distinct approver gets a fresh ToDo.
	Does not suppress core Frappe email/Notification masters (document if they fire).
	"""
	doc.reload()
	expected = _expected_open_assignee(doc)
	open_todos = frappe.get_all(
		"ToDo",
		filters={
			"reference_type": doc.doctype,
			"reference_name": doc.name,
			"status": "Open",
		},
		fields=["name", "allocated_to"],
	)
	for row in open_todos:
		# Keep only todos for the current pending stamped approver.
		if expected and row.allocated_to == expected:
			continue
		todo = frappe.get_doc("ToDo", row.name)
		todo.status = "Closed"
		todo.save(ignore_permissions=True)

	# Terminal / rejected: close everything that remains open.
	if not expected:
		for row in frappe.get_all(
			"ToDo",
			filters={
				"reference_type": doc.doctype,
				"reference_name": doc.name,
				"status": "Open",
			},
			pluck="name",
		):
			todo = frappe.get_doc("ToDo", row)
			todo.status = "Closed"
			todo.save(ignore_permissions=True)
		return

	refresh_pm_assignment_rules(doc)

	# Deduplicate: if multiple Open ToDos exist for the same expected user, keep one.
	kept = False
	for row in frappe.get_all(
		"ToDo",
		filters={
			"reference_type": doc.doctype,
			"reference_name": doc.name,
			"status": "Open",
			"allocated_to": expected,
		},
		fields=["name"],
		order_by="creation desc",
	):
		if not kept:
			kept = True
			continue
		todo = frappe.get_doc("ToDo", row.name)
		todo.status = "Closed"
		todo.save(ignore_permissions=True)


def apply_consecutive_auto_approvals(doc: Document) -> Document:
	"""Loop auto-Approve while the session user remains the stamped next approver."""
	if not doc or not getattr(doc, "doctype", None):
		return doc
	if doc.doctype not in ("PM Request", "PM Clearance"):
		return doc

	hops = 0
	while hops < _MAX_AUTO_SKIP_HOPS:
		hops += 1
		doc.reload()
		try:
			transitions = get_transitions(doc)
		except Exception:
			break
		action = _pick_auto_skip_action(doc, transitions)
		if not action:
			break

		# Fail closed if stamp identity no longer matches (defense in depth).
		if not session_matches_stamped_approver(doc, action):
			break

		# Guard PM Request / Clearance policy the same way as explicit applies.
		if doc.doctype == "PM Request":
			from erpnext_extensions.petty_management.services.request_action_policy import (
				validate_pm_request_workflow_action,
			)

			validate_pm_request_workflow_action(doc, action)
		elif doc.doctype == "PM Clearance":
			from erpnext_extensions.petty_management.services.clearance_action_policy import (
				validate_apply_workflow_action,
			)

			validate_apply_workflow_action(doc, action)

		doc = frappe_apply_workflow(doc, action)
		# Refresh between hops so intermediate same-user ToDos can be closed promptly.
		refresh_pm_assignment_rules(doc)

	finalize_pm_assignments_after_auto_skip(doc)
	return doc
