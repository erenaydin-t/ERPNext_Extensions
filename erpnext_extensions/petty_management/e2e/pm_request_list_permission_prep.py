# Copyright (c) 2026, ERPNext Extensions contributors
"""Prep restricted Petty Management User for PM Request list Playwright (v4.1.3)."""

from __future__ import annotations

import frappe
from frappe.utils import today
from frappe.utils.password import update_password

from erpnext_extensions.petty_management.tests import test_pm_clearance as tpm

PASSWORD = "pm_sec_test_1"
RESTRICTED_EMAIL = "pm_list_desk_v413@example.com"
MANAGER_EMAIL = "pm_list_mgr_desk_v413@example.com"


def _ensure_role(role: str) -> None:
	if not frappe.db.exists("Role", role):
		frappe.get_doc({"doctype": "Role", "role_name": role}).insert(ignore_permissions=True)


def _ensure_user(email: str, roles: list[str]) -> str:
	if not frappe.db.exists("User", email):
		u = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": email.split("@")[0][:40],
				"send_welcome_email": 0,
				"user_type": "System User",
			}
		)
		u.insert(ignore_permissions=True)
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


@frappe.whitelist()
def prepare_pm_request_list_restricted() -> dict:
	"""Create restricted PM User + own request (+ other holder request that must stay hidden)."""
	frappe.set_user("Administrator")
	tpm._ensure_company_context()
	if not tpm.COMPANY:
		frappe.throw("No company")

	# Desk needs Account read for some form paths; keep elevated roles OFF for restricted user.
	restricted = _ensure_user(
		RESTRICTED_EMAIL,
		["Petty Management User", "Accounts User", "Employee"],
	)
	# Operational unrestricted PM role (Accountant) — no System Manager
	accountant = _ensure_user(
		"pm_list_accountant_desk_v413@example.com",
		["Petty Management Accountant", "Accounts User"],
	)
	manager = _ensure_user(
		MANAGER_EMAIL,
		["Petty Management Manager", "Petty Management User", "Accounts User"],
	)

	emp = tpm._make_employee()
	frappe.db.set_value("Employee", emp, "user_id", restricted, update_modified=False)
	tpm._make_holder(emp)

	req = frappe.new_doc("PM Request")
	req.company = tpm.COMPANY
	req.employee = emp
	req.transaction_date = today()
	req.append("details", {"description": "v413 desk list", "advance_amount": 12000})
	req.insert(ignore_permissions=True)
	frappe.db.set_value(
		"PM Request",
		req.name,
		{
			"manager_approver": manager,
			"ceo_approver": manager,
			"finance_approver": accountant,
		},
		update_modified=False,
	)

	other_emp = tpm._make_employee()
	tpm._make_holder(other_emp)
	other = frappe.new_doc("PM Request")
	other.company = tpm.COMPANY
	other.employee = other_emp
	other.transaction_date = today()
	other.append("details", {"description": "v413 other holder", "advance_amount": 99000})
	other.insert(ignore_permissions=True)
	frappe.db.commit()

	return {
		"company": tpm.COMPANY,
		"password": PASSWORD,
		"restricted": {"email": restricted, "password": PASSWORD},
		"accountant": {"email": accountant, "password": PASSWORD},
		"manager": {"email": manager, "password": PASSWORD},
		"administrator": {"email": "Administrator", "password": "admin"},
		"own_pm_request": req.name,
		"other_pm_request": other.name,
		"employee": emp,
	}
