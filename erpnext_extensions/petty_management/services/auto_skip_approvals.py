# Copyright (c) 2026, ERPNext Extensions contributors
"""Consecutive same-user approval auto-skip (v4.1.4).

After an explicit Approve action, while the session user is still the stamped
approver for the *next* Approve transition (and holds that transition's Allowed
Role), automatically apply that Approve via normal ``apply_workflow``.

Never auto-applies Reject, funding, Close, or Payment Entry actions.
Each hop leaves normal Workflow Action history / Version / Timeline and refreshes
Assignment Rules so ToDos are not orphaned.
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

_MAX_AUTO_SKIP_HOPS = 5


def _pick_auto_skip_action(transitions: list) -> str | None:
	"""Return one Approve action the current user may take, preferring canonical names."""
	actions = []
	for t in transitions or []:
		action = (t.get("action") if isinstance(t, dict) else getattr(t, "action", None)) or ""
		if action in PM_AUTO_SKIP_APPROVE_ACTIONS:
			actions.append(action)
	if not actions:
		return None
	# Prefer PM Finance Approve over alias PM Approve when both appear.
	if "PM Finance Approve" in actions:
		return "PM Finance Approve"
	return actions[0]


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


def apply_consecutive_auto_approvals(doc: Document) -> Document:
	"""Loop auto-Approve while the session user remains eligible; never Reject."""
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
		action = _pick_auto_skip_action(transitions)
		if not action:
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
		refresh_pm_assignment_rules(doc)

	return doc
