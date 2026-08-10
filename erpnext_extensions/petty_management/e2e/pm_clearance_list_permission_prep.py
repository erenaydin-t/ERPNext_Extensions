# Copyright (c) 2026, ERPNext Extensions contributors
"""Prep restricted holder + named manager for PM Clearance list Playwright (v4.1.3)."""

from __future__ import annotations

import frappe
from frappe.utils import today
from frappe.utils.password import update_password

from erpnext_extensions.petty_management.services.workflow_utils import resolve_workflow_state_link
from erpnext_extensions.petty_management.tests import test_pm_clearance as tpm

PASSWORD = "pm_sec_test_1"
HOLDER = "pm_clr_desk_holder_v413@example.com"
MANAGER = "pm_clr_desk_mgr_v413@example.com"
NO_EMP = "pm_clr_desk_noemp_v413@example.com"


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


@frappe.whitelist()
def prepare_pm_clearance_list_permission() -> dict:
	frappe.set_user("Administrator")
	tpm._ensure_company_context()
	if not tpm.COMPANY:
		frappe.throw("No company")

	holder = _ensure_user(HOLDER, ["Petty Management User", "Accounts User", "Employee"])
	manager = _ensure_user(
		MANAGER,
		["Petty Management User", "Expense Approver", "Accounts User"],
	)
	finance = _ensure_user(
		"pm_clr_desk_fin_v413@example.com",
		["Petty Management User", "Accounts User"],
	)
	accountant = _ensure_user(
		"pm_clr_desk_accountant_v413@example.com",
		["Petty Management Accountant", "Accounts User"],
	)
	no_emp = _ensure_user(NO_EMP, ["Petty Management User", "Accounts User"])
	frappe.db.sql("update `tabEmployee` set user_id=null where user_id=%s", no_emp)
	frappe.db.commit()

	emp = tpm._make_employee()
	frappe.db.set_value("Employee", emp, "user_id", holder, update_modified=False)
	frappe.db.set_value("Employee", emp, "expense_approver", manager, update_modified=False)
	tpm._make_holder(emp)

	other_emp = tpm._make_employee()
	tpm._make_holder(other_emp)

	cl = frappe.new_doc("PM Clearance")
	cl.company = tpm.COMPANY
	cl.employee = emp
	cl.transaction_date = today()
	cl.flags.ignore_mandatory = True
	cl.flags.ignore_validate = True
	cl.insert(ignore_permissions=True)
	frappe.db.set_value(
		"PM Clearance",
		cl.name,
		{
			"manager_approver": manager,
			"finance_approver": finance,
			"workflow_state": resolve_workflow_state_link("Pending Manager Approval")
			or "Pending Manager Approval",
			"status": "Pending Approval",
			"docstatus": 1,
		},
		update_modified=False,
	)

	other = frappe.new_doc("PM Clearance")
	other.company = tpm.COMPANY
	other.employee = other_emp
	other.transaction_date = today()
	other.flags.ignore_mandatory = True
	other.flags.ignore_validate = True
	other.insert(ignore_permissions=True)
	frappe.db.commit()

	return {
		"company": tpm.COMPANY,
		"password": PASSWORD,
		"holder": {"email": holder, "password": PASSWORD},
		"manager": {"email": manager, "password": PASSWORD},
		"finance": {"email": finance, "password": PASSWORD},
		"accountant": {"email": accountant, "password": PASSWORD},
		"no_emp": {"email": no_emp, "password": PASSWORD},
		"own_pm_clearance": cl.name,
		"other_pm_clearance": other.name,
		"employee": emp,
	}
