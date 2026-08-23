# Copyright (c) 2026, Farbod Siyahpoosh and contributors
# For license information, please see license.txt

"""Petty Management list and document permissions.

``permission_query_conditions`` narrows **list / report** queries.

``has_permission`` on the document controller can **deny** access (return False); it never grants
extra rights beyond Role Permissions / Workflow.

Visibility model (v4.1.4):

- **Administrator** / **System Manager**: unrestricted PM visibility (break-glass).
- **Operational PM Visibility Role** (PM Settings, default Petty Management Accountant): same
  *document visibility* as Administrator for PM Request / PM Clearance, without Administrator
  system privileges. Does **not** bypass Workflow transition rules or DocPerm submit/cancel.
- Everyone else: row filter = own Employee **or** stamped named approver fields.

Functional workflow roles (v4.1.4 — only two):

- Petty Management User — submit + manager/CEO approve (plus stamped-user condition)
- Petty Management Accountant — finance approve (plus stamped finance_approver)

Legacy Manager / Admin / Auditor remain installed but deprecated (no unique DocPerm).
"""

from __future__ import annotations

import frappe

# Fallback when PM Settings field is missing or empty (v4.1.3 default behaviour).
DEFAULT_OPERATIONAL_PM_VISIBILITY_ROLE = "Petty Management Accountant"


def get_operational_pm_visibility_role() -> str:
	"""Role that bypasses PM Request / Clearance row filters (from PM Settings)."""
	try:
		if not frappe.db.exists("DocType", "PM Settings"):
			return DEFAULT_OPERATIONAL_PM_VISIBILITY_ROLE
		meta = frappe.get_meta("PM Settings")
		if not meta.has_field("operational_pm_visibility_role"):
			return DEFAULT_OPERATIONAL_PM_VISIBILITY_ROLE
		role = frappe.db.get_single_value("PM Settings", "operational_pm_visibility_role")
		if isinstance(role, str) and role.strip():
			return role.strip()
	except Exception:
		pass
	return DEFAULT_OPERATIONAL_PM_VISIBILITY_ROLE


def _is_pm_visibility_unrestricted(user: str | None = None) -> bool:
	"""Return True when PM Request/Clearance lists must not apply employee/approver filters.

	Administrator and the configured operational PM role share this path. Does not grant
	Workflow or DocPerm rights beyond what those roles already have.
	"""
	user = user or frappe.session.user
	if user == "Administrator":
		return True
	roles = set(frappe.get_roles(user))
	if "System Manager" in roles:
		return True
	return get_operational_pm_visibility_role() in roles


def _user_employee(user: str | None = None) -> str | None:
	"""Resolve Employee for a User without selecting a missing ``User.employee`` column.

	HRMS / ERPNext link users through ``Employee.user_id``. Some sites also have a custom
	``User.employee`` field; prefer ``user_id`` and only read ``User.employee`` when the
	column exists. Never raise OperationalError from a missing column during list queries.
	"""
	user = user or frappe.session.user
	if user in ("Administrator", "Guest"):
		return None

	emp = frappe.db.get_value("Employee", {"user_id": user, "status": ("!=", "Left")}, "name")
	if emp:
		return emp
	emp = frappe.db.get_value("Employee", {"user_id": user}, "name")
	if emp:
		return emp

	if frappe.db.has_column("User", "employee"):
		return frappe.db.get_value("User", user, "employee")
	return None


def _petty_user_restricted(user: str | None = None) -> bool:
	"""True when row filters apply (not Administrator / System Manager / operational role)."""
	return not _is_pm_visibility_unrestricted(user)


def _escape_user(user: str) -> str:
	return frappe.db.escape(user, percent=False)


def _restricted_row_conditions(doctype: str, user: str) -> str:
	"""OR of own-employee scope and named-approver stamps."""
	user = user or frappe.session.user
	table = f"`tab{doctype}`"
	parts: list[str] = []

	emp = _user_employee(user)
	if emp:
		parts.append(f"{table}.employee = {frappe.db.escape(emp, percent=False)}")

	ue = _escape_user(user)
	parts.append(f"{table}.manager_approver = {ue}")
	parts.append(f"{table}.finance_approver = {ue}")
	if doctype == "PM Request" and frappe.db.has_column(doctype, "ceo_approver"):
		parts.append(f"{table}.ceo_approver = {ue}")

	if not parts:
		return "1=0"
	return "(" + " OR ".join(parts) + ")"


def _clearance_finance_queue_list_condition(user: str) -> str:
	"""Pending Finance Review clearances visible to users with the review role."""
	from erpnext_extensions.petty_management.services.clearance_finance_review import (
		user_has_clearance_finance_review_role,
	)
	from erpnext_extensions.petty_management.services.workflow_utils import resolve_workflow_state_link

	if not user_has_clearance_finance_review_role(user):
		return ""
	pending = resolve_workflow_state_link("Pending Finance Review")
	if not pending:
		return ""
	return f"`tabPM Clearance`.workflow_state = {frappe.db.escape(pending, percent=False)}"


def pm_request_permission_query_conditions(user: str | None = None, doctype: str | None = None) -> str:
	if _is_pm_visibility_unrestricted(user):
		return ""
	return _restricted_row_conditions("PM Request", user or frappe.session.user)


def pm_clearance_permission_query_conditions(user: str | None = None, doctype: str | None = None) -> str:
	if _is_pm_visibility_unrestricted(user):
		return ""
	user = user or frappe.session.user
	base = _restricted_row_conditions("PM Clearance", user)
	queue = _clearance_finance_queue_list_condition(user)
	if queue:
		return f"({base} OR {queue})"
	return base


def has_pm_request_permission(doc, ptype=None, user=None, debug=False):
	if _is_pm_visibility_unrestricted(user):
		return True
	return _check_restricted_doc_access(doc, user, include_ceo=True)


def has_pm_clearance_permission(doc, ptype=None, user=None, debug=False):
	if _is_pm_visibility_unrestricted(user):
		return True
	user = user or frappe.session.user
	if getattr(doc, "doctype", None) == "PM Clearance" and ptype in ("write", "submit"):
		from erpnext_extensions.petty_management.services.clearance_finance_review import (
			clearance_is_pending_finance_review,
			user_has_clearance_finance_review_role,
		)

		if user_has_clearance_finance_review_role(user):
			if clearance_is_pending_finance_review(doc):
				return True
			before = doc.get_doc_before_save() if hasattr(doc, "get_doc_before_save") else None
			if before and clearance_is_pending_finance_review(before):
				return True
			# Workflow apply sets next_state before save(); finance_approver still blank.
			if (getattr(doc, "status", None) or "").strip() == "Pending Approval" and not (
				getattr(doc, "finance_approver", None) or ""
			).strip():
				return True
	return _check_restricted_doc_access(doc, user, include_ceo=False)


def _check_restricted_doc_access(doc, user, *, include_ceo: bool) -> bool:
	if not doc:
		return True
	user = user or frappe.session.user
	emp = _user_employee(user)
	if emp and getattr(doc, "employee", None) == emp:
		return True
	if getattr(doc, "manager_approver", None) == user:
		return True
	if getattr(doc, "finance_approver", None) == user:
		return True
	if include_ceo and getattr(doc, "ceo_approver", None) == user:
		return True
	if getattr(doc, "doctype", None) == "PM Clearance":
		from erpnext_extensions.petty_management.services.clearance_finance_review import (
			clearance_is_pending_finance_review,
			user_has_clearance_finance_review_role,
		)

		if clearance_is_pending_finance_review(doc) and user_has_clearance_finance_review_role(user):
			return True
	return False
