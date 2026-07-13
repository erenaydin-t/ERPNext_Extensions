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


def assert_party_analysis_enabled() -> None:
	assert_feature_enabled()
	if not frappe.get_single_value("Iran Accounting Settings", "party_analysis_enabled"):
		frappe.throw(
			_("Party analysis is not enabled. Configure Iran Accounting Settings."),
			frappe.ValidationError,
		)


def assert_dimension_analysis_enabled() -> None:
	assert_feature_enabled()
	if not frappe.get_single_value("Iran Accounting Settings", "dimension_analysis_enabled"):
		frappe.throw(
			_("Dimension analysis is not enabled. Configure Iran Accounting Settings."),
			frappe.ValidationError,
		)


def assert_voucher_analysis_enabled() -> None:
	assert_feature_enabled()
	if not frappe.get_single_value("Iran Accounting Settings", "voucher_analysis_enabled"):
		frappe.throw(
			_("Voucher analysis is not enabled. Configure Iran Accounting Settings."),
			frappe.ValidationError,
		)


def assert_gl_navigation_allowed() -> None:
	assert_feature_enabled()
	if not frappe.get_single_value("Iran Accounting Settings", "allow_gl_entry_navigation"):
		frappe.throw(
			_("GL Entry navigation is disabled. Configure Iran Accounting Settings."),
			frappe.ValidationError,
		)


def assert_unified_party_enabled() -> None:
	assert_feature_enabled()
	if not frappe.get_single_value("Iran Accounting Settings", "unified_party_enabled"):
		frappe.throw(
			_("Unified Party analysis is not enabled. Configure Iran Accounting Settings."),
			frappe.ValidationError,
		)


def assert_unified_party_suggestions_allowed() -> None:
	assert_unified_party_enabled()
	if frappe.session.user == "Administrator":
		return
	roles = set(frappe.get_roles(frappe.session.user))
	if "Accounts Manager" not in roles:
		frappe.throw(_("Not permitted to view unified party suggestions."), frappe.PermissionError)


def assert_currency_analysis_enabled() -> None:
	assert_feature_enabled()
	if not frappe.get_single_value("Iran Accounting Settings", "currency_analysis_enabled"):
		frappe.throw(
			_("Currency analysis is not enabled. Configure Iran Accounting Settings."),
			frappe.ValidationError,
		)
