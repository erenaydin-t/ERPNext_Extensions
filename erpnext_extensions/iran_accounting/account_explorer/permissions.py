# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

import frappe
from frappe import _

ALLOWED_ROLES = frozenset({"Accounts User", "Accounts Manager", "Auditor"})


def assert_accounts_role() -> None:
	if frappe.session.user == "Administrator":
		return
	roles = set(frappe.get_roles(frappe.session.user))
	if not roles.intersection(ALLOWED_ROLES):
		frappe.throw(_("Not permitted to access Account Explorer."), frappe.PermissionError)


def assert_company_allowed(company: str) -> None:
	if not frappe.has_permission("GL Entry", "read"):
		frappe.throw(_("Not permitted to read GL Entry."), frappe.PermissionError)
	if not frappe.db.exists("Company", company):
		frappe.throw(_("Company {0} does not exist").format(company))
	if frappe.session.user == "Administrator":
		return
	if not frappe.has_permission("Company", "read", company):
		frappe.throw(_("Not permitted for company {0}").format(company), frappe.PermissionError)


def assert_feature_enabled() -> None:
	if not frappe.get_single_value("Iran Accounting Settings", "account_explorer_enabled"):
		frappe.throw(
			_("Account Explorer is not enabled. Configure Iran Accounting Settings."),
			frappe.ValidationError,
		)
