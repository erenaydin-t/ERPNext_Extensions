# Copyright (c) 2026, ERPNext Extensions contributors
"""Prep users + PM Request / Clearance for multi-approval Playwright E2E (v4.0.2)."""

from __future__ import annotations

import frappe
from frappe.utils import today

from erpnext_extensions.petty_management.services.workflow_utils import (
	apply_pm_workflow,
	resolve_workflow_state_link,
)
from erpnext_extensions.petty_management.tests import test_pm_clearance as tpm


def _ensure_user(email: str, roles: list[str], password: str = "pm_sec_test_1") -> str:
	if not frappe.db.exists("User", email):
		u = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": email.split("@")[0],
				"send_welcome_email": 0,
				"user_type": "System User",
			}
		)
		u.insert(ignore_permissions=True)
		u.new_password = password
		u.save(ignore_permissions=True)
	else:
		from frappe.utils.password import update_password

		update_password(email, password)
	user = frappe.get_doc("User", email)
	for role in roles:
		if not frappe.db.exists("Role", role):
			frappe.get_doc({"doctype": "Role", "role_name": role}).insert(ignore_permissions=True)
		if role not in [r.role for r in user.roles]:
			user.append("roles", {"role": role})
	user.enabled = 1
	user.save(ignore_permissions=True)
	frappe.db.commit()
	return email


def _configure_settings(manager: str, ceo: str, finance: str) -> None:
	settings = frappe.get_single("PM Settings")
	settings.db_set("ceo_approver", ceo, update_modified=False)
	settings.db_set("finance_manager", finance, update_modified=False)
	settings.db_set("finance_supervisor", finance, update_modified=False)
	settings.db_set("require_named_manager_approver", 1, update_modified=False)
	frappe.db.commit()


@frappe.whitelist()
def prepare_pm_request_multi_approval() -> dict:
	"""Create draft-ready Approved chain start: holder submits → Pending Manager."""
	frappe.set_user("Administrator")
	tpm._ensure_company_context()
	if not tpm.COMPANY:
		frappe.throw("No company")

	# Accounts User is required so holder validate can read Account balances (get_balance_on).
	desk_roles = ["Accounts User", "Employee", "System Manager"]
	holder = _ensure_user(
		"pm_holder_v402_e2e@example.com",
		["Petty Management User", *desk_roles],
	)
	manager = _ensure_user(
		"pm_mgr_v402_e2e@example.com",
		["Petty Management Manager", "Petty Management User", "Expense Approver", *desk_roles],
	)
	ceo = _ensure_user(
		"pm_ceo_v402_e2e@example.com",
		["Petty Management Manager", *desk_roles],
	)
	finance = _ensure_user(
		"pm_fin_v402_e2e@example.com",
		["Petty Management Accountant", *desk_roles],
	)
	_configure_settings(manager, ceo, finance)

	emp = tpm._make_employee()
	frappe.db.set_value("Employee", emp, "expense_approver", manager, update_modified=False)
	frappe.db.set_value("Employee", emp, "user_id", holder, update_modified=False)
	tpm._make_holder(emp)

	# Link holder user to employee for desk create if needed
	req = frappe.new_doc("PM Request")
	req.company = tpm.COMPANY
	req.employee = emp
	req.transaction_date = today()
	req.append("details", {"description": "v402 playwright multi approval", "advance_amount": 25000})
	req.insert(ignore_permissions=True)
	frappe.db.commit()

	return {
		"pm_request": req.name,
		"employee": emp,
		"company": tpm.COMPANY,
		"password": "pm_sec_test_1",
		"holder": {"email": holder, "password": "pm_sec_test_1"},
		"manager": {"email": manager, "password": "pm_sec_test_1"},
		"ceo": {"email": ceo, "password": "pm_sec_test_1"},
		"finance": {"email": finance, "password": "pm_sec_test_1"},
	}


@frappe.whitelist()
def prepare_pm_clearance_multi_approval() -> dict:
	"""Funded request + draft PM Clearance ready for multi-approval Desk E2E."""
	frappe.set_user("Administrator")
	tpm._ensure_company_context()
	prep = prepare_pm_request_multi_approval()
	manager = prep["manager"]["email"]
	finance = prep["finance"]["email"]
	emp = prep["employee"]

	# Fast-path request to Finance Approved + fund
	pm_request, pe = tpm._fund_pm_request(emp, 100_000.0)
	waiting = resolve_workflow_state_link("Finance Approved")
	frappe.db.set_value(
		"PM Request",
		pm_request,
		{
			"workflow_state": waiting,
			"status": "Waiting for Payment",
			"payment_status": "Paid",
			"manager_approver": manager,
			"ceo_approver": prep["ceo"]["email"],
			"finance_approver": finance,
		},
		update_modified=False,
	)

	pi = tpm._make_pi_outstanding(8_000)
	pi.insert(ignore_permissions=True)
	pi.submit()

	cl = tpm._lifecycle_base_clearance(emp, pi, 8_000)
	cl.append("request_allocations", {"pm_request": pm_request, "allocated_amount": 8_000})
	cl.insert(ignore_permissions=True)
	frappe.db.commit()

	return {
		**prep,
		"pm_request": pm_request,
		"payment_entry": pe,
		"purchase_invoice": pi.name,
		"pm_clearance": cl.name,
		"settle_amount": 8000,
	}
