# Copyright (c) 2026, ERPNext Extensions contributors
"""Prep unpaid / partial / paid / closed PM Requests for funding-status UX Playwright."""

from __future__ import annotations

import frappe
from frappe.utils.password import update_password

from erpnext_extensions.petty_management.services.funding_service import close_pm_request
from erpnext_extensions.petty_management.services.request_action_policy import (
	compute_pm_request_action_flags,
)
from erpnext_extensions.petty_management.tests import test_pm_clearance as tpm
from erpnext_extensions.petty_management.tests.test_pm_request_multi_pe import (
	_create_funding_pe,
	_ensure_pm_settings_bank,
	_new_submitted_request,
	_sync_funding_fields,
)

PASSWORD = "pm_sec_test_1"
USER = "pm_funding_status_ux_e2e@example.com"


def _ensure_user() -> dict:
	if not frappe.db.exists("User", USER):
		doc = frappe.get_doc(
			{
				"doctype": "User",
				"email": USER,
				"first_name": "PM",
				"last_name": "FundingUX",
				"send_welcome_email": 0,
				"user_type": "System User",
				"enabled": 1,
			}
		)
		doc.insert(ignore_permissions=True)
	else:
		doc = frappe.get_doc("User", USER)
	doc.roles = []
	for role in (
		"Accounts User",
		"Petty Management User",
		"Petty Management Manager",
		"Petty Management Accountant",
	):
		if not frappe.db.exists("Role", role):
			frappe.get_doc({"doctype": "Role", "role_name": role}).insert(ignore_permissions=True)
		doc.append("roles", {"role": role})
	doc.enabled = 1
	doc.save(ignore_permissions=True)
	update_password(USER, PASSWORD)
	frappe.db.commit()
	return {"email": USER, "password": PASSWORD}


def _flags_snapshot(name: str) -> dict:
	doc = frappe.get_doc("PM Request", name)
	f = compute_pm_request_action_flags(doc)
	return {
		"name": name,
		"status": doc.status,
		"payment_status": doc.payment_status,
		"workflow_state": doc.workflow_state,
		"is_closed": int(doc.is_closed or 0),
		"remaining_to_pay": float(doc.remaining_to_pay or 0),
		"total_paid_amount": float(doc.total_paid_amount or 0),
		"business_status_headline": f.get("business_status_headline"),
		"ui_messages": f.get("ui_messages") or [],
		"can_create_payment_entry": bool(f.get("can_create_payment_entry")),
	}


@frappe.whitelist()
def prepare_pm_request_funding_status_ux() -> dict:
	frappe.set_user("Administrator")
	tpm._ensure_company_context()
	tpm._ensure_petty_account()
	_ensure_pm_settings_bank()
	user = _ensure_user()

	emp_u = tpm._make_employee()
	tpm._make_holder(emp_u)
	unpaid = _new_submitted_request(emp_u, 10_000)
	_sync_funding_fields(unpaid)

	emp_p = tpm._make_employee()
	tpm._make_holder(emp_p)
	partial = _new_submitted_request(emp_p, 10_000)
	_create_funding_pe(partial, 4_000)
	_sync_funding_fields(partial)

	emp_f = tpm._make_employee()
	tpm._make_holder(emp_f)
	funded = _new_submitted_request(emp_f, 10_000)
	_create_funding_pe(funded, 10_000)
	_sync_funding_fields(funded)

	emp_c = tpm._make_employee()
	tpm._make_holder(emp_c)
	closed = _new_submitted_request(emp_c, 10_000)
	_create_funding_pe(closed, 10_000)
	_sync_funding_fields(closed)
	close_pm_request(closed)
	frappe.db.commit()

	return {
		"user": user,
		"unpaid": _flags_snapshot(unpaid),
		"partial": _flags_snapshot(partial),
		"funded": _flags_snapshot(funded),
		"closed": _flags_snapshot(closed),
	}
