# Copyright (c) 2026, Farbod Siyahpoosh and contributors
# For license information, please see license.txt

"""Petty Management list and document permissions.

``permission_query_conditions`` narrows **list / report** queries for users who are restricted.

``has_permission`` on the document controller can **deny** access (return False); it never grants
extra rights beyond Role Permissions.

Restricted users:
  Only **Petty Management User** when they do **not** also hold any *elevated* Petty (or break-glass)
  role. Those users see only documents where ``employee`` matches the Employee linked to the User
  via ``Employee.user_id`` (and optionally ``User.employee`` when that column exists).

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


def pm_request_permission_query_conditions(user: str | None = None, doctype: str | None = None) -> str:
	if not _petty_user_restricted(user):
		return ""
	emp = _user_employee(user)
	if not emp:
		return "1=0"
	return f"`tabPM Request`.employee = {frappe.db.escape(emp, percent=False)}"


def pm_clearance_permission_query_conditions(user: str | None = None, doctype: str | None = None) -> str:
	if not _petty_user_restricted(user):
		return ""
	emp = _user_employee(user)
	if not emp:
		return "1=0"
	return f"`tabPM Clearance`.employee = {frappe.db.escape(emp, percent=False)}"


def has_pm_request_permission(doc, ptype=None, user=None, debug=False):
	return _check_own_employee_doc(doc, user, "employee")


def has_pm_clearance_permission(doc, ptype=None, user=None, debug=False):
	return _check_own_employee_doc(doc, user, "employee")


def _check_own_employee_doc(doc, user, employee_field: str):
	if not doc:
		return True
	if not _petty_user_restricted(user):
		return True
	emp = _user_employee(user)
	if not emp:
		return False
	return getattr(doc, employee_field, None) == emp
