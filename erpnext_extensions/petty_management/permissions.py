# Copyright (c) 2026, Farbod Siyahpoosh and contributors
# For license information, please see license.txt

"""Petty Management list and document permissions.

``permission_query_conditions`` narrows **list / report** queries for users who are restricted.

``has_permission`` on the document controller can **deny** access (return False); it never grants
extra rights beyond Role Permissions.

Restricted users:
  Only **Petty Management User** when they do **not** also hold any *elevated* Petty (or break-glass)
  role. Those users see documents where:

  - ``employee`` matches the Employee linked via ``Employee.user_id`` (or ``User.employee`` when
    that column exists), **or**
  - they are a stamped named approver (``manager_approver`` / ``ceo_approver`` /
    ``finance_approver``).

  Users with no Employee link and who are not stamped as approver on a row are fail-closed
  (``1=0`` / deny).

Elevated roles (no employee-scoped list filter from this module):
  Petty Management Manager, Admin, Accountant, Auditor, and System Manager.
  They can see all PM Request / PM Clearance rows allowed by DocPerm.

Administrator bypasses permission checks in Frappe as usual.

DocPerm on PM Request / PM Clearance intentionally omits generic ERPNext Accounts roles so broad
accounting roles do not gain access unless given a Petty Management role (or Administrator).
"""

from __future__ import annotations

import frappe


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
	# Fallback: any status if active filter missed (disabled / Left still usable for scoping)
	emp = frappe.db.get_value("Employee", {"user_id": user}, "name")
	if emp:
		return emp

	if frappe.db.has_column("User", "employee"):
		return frappe.db.get_value("User", user, "employee")
	return None


def _petty_user_restricted(user: str | None = None) -> bool:
	user = user or frappe.session.user
	if user == "Administrator":
		return False
	roles = set(frappe.get_roles(user))
	elevated = {
		"Petty Management Manager",
		"Petty Management Admin",
		"Petty Management Accountant",
		"Petty Management Auditor",
		"System Manager",
	}
	if roles & elevated:
		return False
	return "Petty Management User" in roles


def _escape_user(user: str) -> str:
	return frappe.db.escape(user, percent=False)


def _restricted_row_conditions(doctype: str, user: str) -> str:
	"""OR of own-employee scope and named-approver stamps. Fail-closed when empty."""
	user = user or frappe.session.user
	table = f"`tab{doctype}`"
	parts: list[str] = []

	emp = _user_employee(user)
	if emp:
		parts.append(f"{table}.employee = {frappe.db.escape(emp, percent=False)}")

	# Named approvers (Assignment Rule / workflow stamps) must open assigned docs
	# even when they have only Petty Management User (no elevated role / no Employee).
	ue = _escape_user(user)
	parts.append(f"{table}.manager_approver = {ue}")
	parts.append(f"{table}.finance_approver = {ue}")
	if doctype == "PM Request" and frappe.db.has_column(doctype, "ceo_approver"):
		parts.append(f"{table}.ceo_approver = {ue}")

	if not parts:
		return "1=0"
	return "(" + " OR ".join(parts) + ")"


def pm_request_permission_query_conditions(user: str | None = None, doctype: str | None = None) -> str:
	if not _petty_user_restricted(user):
		return ""
	return _restricted_row_conditions("PM Request", user or frappe.session.user)


def pm_clearance_permission_query_conditions(user: str | None = None, doctype: str | None = None) -> str:
	if not _petty_user_restricted(user):
		return ""
	return _restricted_row_conditions("PM Clearance", user or frappe.session.user)


def has_pm_request_permission(doc, ptype=None, user=None, debug=False):
	return _check_restricted_doc_access(doc, user, include_ceo=True)


def has_pm_clearance_permission(doc, ptype=None, user=None, debug=False):
	return _check_restricted_doc_access(doc, user, include_ceo=False)


def _check_restricted_doc_access(doc, user, *, include_ceo: bool) -> bool:
	if not doc:
		return True
	if not _petty_user_restricted(user):
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
	return False
