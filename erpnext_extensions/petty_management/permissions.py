# Copyright (c) 2026, Farbod Siyahpoosh and contributors
# For license information, please see license.txt

import frappe


def _user_employee(user: str | None = None) -> str | None:
	user = user or frappe.session.user
	if user in ("Administrator", "Guest"):
		return None
	return frappe.db.get_value("User", user, "employee")


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


def pm_request_permission_query_conditions(user: str | None = None) -> str:
	if not _petty_user_restricted(user):
		return ""
	emp = _user_employee(user)
	if not emp:
		return "1=0"
	return f"`tabPM Request`.employee = {frappe.db.escape(emp)}"


def pm_clearance_permission_query_conditions(user: str | None = None) -> str:
	if not _petty_user_restricted(user):
		return ""
	emp = _user_employee(user)
	if not emp:
		return "1=0"
	return f"`tabPM Clearance`.employee = {frappe.db.escape(emp)}"


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
