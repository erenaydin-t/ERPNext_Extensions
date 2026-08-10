# Copyright (c) 2026, ERPNext Extensions contributors
"""Prep + helpers for configurable Operational PM Visibility Role Playwright."""

from __future__ import annotations

import frappe
from frappe.utils import today
from frappe.utils.password import update_password

from erpnext_extensions.petty_management.permissions import DEFAULT_OPERATIONAL_PM_VISIBILITY_ROLE
from erpnext_extensions.petty_management.tests import test_pm_clearance as tpm

PASSWORD = "pm_sec_test_1"
MANAGER_EMAIL = "pm_viscfg_pw_mgr_v413@example.com"
ACCOUNTANT_EMAIL = "pm_viscfg_pw_acct_v413@example.com"


def _ensure_role(role: str) -> None:
	if not frappe.db.exists("Role", role):
		frappe.get_doc({"doctype": "Role", "role_name": role}).insert(ignore_permissions=True)


def _ensure_user(email: str, roles: list[str]) -> str:
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": email.split("@")[0][:40],
				"send_welcome_email": 0,
				"user_type": "System User",
			}
		).insert(ignore_permissions=True)
	update_password(email, PASSWORD)
	user = frappe.get_doc("User", email)
	user.roles = []
	for role in roles:
		_ensure_role(role)
		user.append("roles", {"role": role})
	user.enabled = 1
	user.save(ignore_permissions=True)
	frappe.db.commit()
	return email


def _set_visibility_role(role: str) -> str:
	frappe.db.set_single_value("PM Settings", "operational_pm_visibility_role", role)
	frappe.clear_cache(doctype="PM Settings")
	return role


@frappe.whitelist()
def prepare_pm_visibility_role_setting() -> dict:
	"""Seed Manager/Accountant users + two PM Requests; reset visibility role to Accountant."""
	frappe.set_user("Administrator")
	tpm._ensure_company_context()
	if not tpm.COMPANY:
		frappe.throw("No company")
	if not frappe.get_meta("PM Settings").has_field("operational_pm_visibility_role"):
		frappe.throw("operational_pm_visibility_role missing — run migrate")

	_set_visibility_role(DEFAULT_OPERATIONAL_PM_VISIBILITY_ROLE)

	manager = _ensure_user(
		MANAGER_EMAIL,
		["Petty Management Manager", "Petty Management User", "Accounts User"],
	)
	accountant = _ensure_user(
		ACCOUNTANT_EMAIL,
		["Petty Management Accountant", "Accounts User"],
	)
	frappe.db.sql("update `tabEmployee` set user_id=null where user_id in (%s, %s)", (manager, accountant))

	emp = tpm._make_employee()
	tpm._make_holder(emp)
	own = frappe.new_doc("PM Request")
	own.company = tpm.COMPANY
	own.employee = emp
	own.transaction_date = today()
	own.append("details", {"description": "viscfg own", "advance_amount": 11000})
	own.insert(ignore_permissions=True)
	frappe.db.set_value(
		"PM Request",
		own.name,
		{"manager_approver": manager, "finance_approver": accountant},
		update_modified=False,
	)

	other_emp = tpm._make_employee()
	tpm._make_holder(other_emp)
	other = frappe.new_doc("PM Request")
	other.company = tpm.COMPANY
	other.employee = other_emp
	other.transaction_date = today()
	other.append("details", {"description": "viscfg other", "advance_amount": 88000})
	other.insert(ignore_permissions=True)
	frappe.db.commit()

	return {
		"company": tpm.COMPANY,
		"password": PASSWORD,
		"manager": {"email": manager, "password": PASSWORD},
		"accountant": {"email": accountant, "password": PASSWORD},
		"own_pm_request": own.name,
		"other_pm_request": other.name,
		"default_role": DEFAULT_OPERATIONAL_PM_VISIBILITY_ROLE,
		"visibility_role": frappe.db.get_single_value("PM Settings", "operational_pm_visibility_role"),
	}


@frappe.whitelist()
def set_operational_pm_visibility_role(role: str | None = None) -> dict:
	"""Set PM Settings.operational_pm_visibility_role (Administrator)."""
	frappe.set_user("Administrator")
	role = (role or DEFAULT_OPERATIONAL_PM_VISIBILITY_ROLE).strip()
	_ensure_role(role)
	_set_visibility_role(role)
	return {
		"role": role,
		"effective": frappe.db.get_single_value("PM Settings", "operational_pm_visibility_role")
		or DEFAULT_OPERATIONAL_PM_VISIBILITY_ROLE,
	}
