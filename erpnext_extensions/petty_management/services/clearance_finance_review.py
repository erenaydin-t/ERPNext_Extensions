# Copyright (c) 2026, ERPNext Extensions contributors
"""PM Clearance Finance Review role queue (v4.5.3).

Native Workflow + Workflow Action only. No Assignment Rule / ToDo for finance review.
``finance_approver`` is stamped only after a successful Finance Approve/Reject act.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document

from erpnext_extensions.petty_management.services.clearance_action_policy import workflow_state_title
from erpnext_extensions.petty_management.utils import get_pm_settings

DEFAULT_CLEARANCE_FINANCE_REVIEW_ROLE = "Petty Management Clearance Reviewer"

CLEARANCE_FINANCE_WORKFLOW_ACTIONS = frozenset(
	{"PM Finance Approve", "PM Approve", "PM Reject"}
)


def get_clearance_finance_review_role() -> str:
	"""Configured Role for Clearance Finance Review queue (never empty when configured)."""
	settings = get_pm_settings()
	if settings:
		meta = frappe.get_meta("PM Settings")
		if meta.has_field("clearance_finance_review_role"):
			role = getattr(settings, "clearance_finance_review_role", None)
			if isinstance(role, str) and role.strip():
				return role.strip()
	return DEFAULT_CLEARANCE_FINANCE_REVIEW_ROLE


def ensure_clearance_finance_review_role_configured() -> None:
	"""Fail closed when the review role is missing from the site."""
	role = get_clearance_finance_review_role()
	if not role or not frappe.db.exists("Role", role):
		frappe.throw(
			_(
				"Cannot submit PM Clearance: Clearance Finance Review Role "
				"{0} is not configured in Petty Management Settings."
			).format(role or "(empty)"),
			title=_("Finance review role required"),
		)


def user_has_clearance_finance_review_role(user: str | None = None) -> bool:
	user = user or frappe.session.user
	if user == "Administrator":
		return True
	return get_clearance_finance_review_role() in set(frappe.get_roles(user))


def clearance_is_pending_finance_review(doc: Document | str) -> bool:
	if isinstance(doc, str):
		doc = frappe.get_doc("PM Clearance", doc)
	return workflow_state_title(getattr(doc, "workflow_state", None)) == "Pending Finance Review"


def validate_clearance_finance_reviewer(user: str | None = None) -> None:
	"""Server-side guard: session user must hold the configured review role."""
	user = user or frappe.session.user
	if user == "Administrator":
		return
	if not user_has_clearance_finance_review_role(user):
		frappe.throw(
			_("You are not authorized to perform Finance Review on this PM Clearance."),
			title=_("Not permitted"),
			exc=frappe.PermissionError,
		)


def validate_clearance_finance_workflow_action(doc: Document, action: str) -> None:
	"""Role guard for Finance Review workflow actions on PM Clearance."""
	action = (action or "").strip()
	if action not in CLEARANCE_FINANCE_WORKFLOW_ACTIONS:
		return
	if not clearance_is_pending_finance_review(doc):
		return
	validate_clearance_finance_reviewer()


def stamp_clearance_finance_approver_after_act(doc: Document, action: str) -> None:
	"""Audit stamp: record which User completed Finance Review."""
	action = (action or "").strip()
	if action not in CLEARANCE_FINANCE_WORKFLOW_ACTIONS:
		return
	if not getattr(doc, "name", None):
		return
	user = frappe.session.user
	if user == "Administrator":
		return
	frappe.db.set_value(
		"PM Clearance",
		doc.name,
		"finance_approver",
		user,
		update_modified=False,
	)
	doc.finance_approver = user
