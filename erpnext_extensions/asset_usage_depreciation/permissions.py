# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

"""Row-level visibility for Asset Request."""

from __future__ import annotations

import frappe

from erpnext_extensions.asset_usage_depreciation.constants import (
	ROLE_AR_EXECUTIVE,
	ROLE_AR_MANAGER,
	ROLE_AR_PLANNER,
	ROLE_ASSET_MANAGER,
)

UNRESTRICTED_ROLES = {
	"System Manager",
	"Accounts Manager",
	ROLE_ASSET_MANAGER,
	ROLE_AR_PLANNER,
	ROLE_AR_EXECUTIVE,
}


def _user_employee(user: str | None = None) -> str | None:
	user = user or frappe.session.user
	if user in ("Administrator", "Guest"):
		return None
	emp = frappe.db.get_value("Employee", {"user_id": user, "status": ("!=", "Left")}, "name")
	if emp:
		return emp
	return frappe.db.get_value("Employee", {"user_id": user}, "name")


def _is_unrestricted(user: str | None = None) -> bool:
	user = user or frappe.session.user
	if user == "Administrator":
		return True
	roles = set(frappe.get_roles(user))
	return bool(roles & UNRESTRICTED_ROLES)


def asset_request_permission_query_conditions(user: str | None = None, doctype: str | None = None) -> str:
	if _is_unrestricted(user):
		return ""
	user = user or frappe.session.user
	table = "`tabAsset Request`"
	parts = []
	emp = _user_employee(user)
	if emp:
		parts.append(f"{table}.employee = {frappe.db.escape(emp, percent=False)}")
	ue = frappe.db.escape(user, percent=False)
	parts.append(f"{table}.manager_approver = {ue}")
	parts.append(f"{table}.planning_approver = {ue}")
	parts.append(f"{table}.ceo_approver = {ue}")
	parts.append(f"{table}.owner = {ue}")
	if ROLE_AR_MANAGER in frappe.get_roles(user) and emp:
		dept = frappe.db.get_value("Employee", emp, "department")
		if dept:
			parts.append(f"{table}.department = {frappe.db.escape(dept, percent=False)}")
	if not parts:
		return "1=0"
	return "(" + " OR ".join(parts) + ")"


def has_asset_request_permission(doc, ptype=None, user=None, debug=False):
	if _is_unrestricted(user):
		return True
	if not doc:
		return True
	user = user or frappe.session.user
	emp = _user_employee(user)
	if emp and getattr(doc, "employee", None) == emp:
		return True
	if getattr(doc, "owner", None) == user:
		return True
	if getattr(doc, "manager_approver", None) == user:
		return True
	if getattr(doc, "planning_approver", None) == user:
		return True
	if getattr(doc, "ceo_approver", None) == user:
		return True
	if ROLE_AR_MANAGER in frappe.get_roles(user) and emp:
		dept = frappe.db.get_value("Employee", emp, "department")
		if dept and getattr(doc, "department", None) == dept:
			return True
	return False
