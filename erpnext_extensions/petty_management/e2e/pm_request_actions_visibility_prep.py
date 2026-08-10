# Copyright (c) 2026, Farbod Siyahpoosh and contributors
"""Prep fixtures for PM Request Actions visibility Playwright E2E."""

from __future__ import annotations

import frappe
from frappe.utils.password import update_password

from erpnext_extensions.e2e.e2e_fixture import e2e_run_context
from erpnext_extensions.petty_management.tests import test_pm_clearance as tpm
from erpnext_extensions.petty_management.tests.test_pm_request_multi_pe import (
	_create_funding_pe,
	_ensure_pm_settings_bank,
	_new_submitted_request,
	_sync_funding_fields,
)

E2E_USER = "pm_actions_vis_e2e@example.com"
E2E_PASSWORD = "pm_sec_test_1"


def _ensure_e2e_manager_user() -> dict:
	frappe.set_user("Administrator")
	# Prefer proper User.insert so Desk login works (raw SQL users can fail auth).
	if frappe.db.exists("User", E2E_USER):
		frappe.delete_doc("User", E2E_USER, force=True, ignore_permissions=True)
		frappe.db.commit()

	doc = frappe.get_doc(
		{
			"doctype": "User",
			"email": E2E_USER,
			"first_name": "PM",
			"last_name": "ActionsVis",
			"send_welcome_email": 0,
			"user_type": "System User",
			"enabled": 1,
		}
	)
	doc.insert(ignore_permissions=True)
	for role in (
		"Accounts User",
		"Petty Management User",
		"Petty Management Accountant",
	):
		doc.append("roles", {"role": role})
	doc.save(ignore_permissions=True)
	update_password(E2E_USER, E2E_PASSWORD)
	frappe.db.commit()
	return {"email": E2E_USER, "password": E2E_PASSWORD}


@frappe.whitelist()
def prepare_fully_funded_actions_visibility() -> dict:
	"""Approved PM Request with submitted PE, remaining_to_pay=0, plus Desk login user."""
	frappe.set_user("Administrator")
	tpm._ensure_company_context()
	tpm._ensure_petty_account()
	_ensure_pm_settings_bank()
	from erpnext_extensions.patches.post_model_sync.add_petty_management_workflows import execute as ensure_wf

	ensure_wf()

	user = _ensure_e2e_manager_user()
	emp = tpm._make_employee()
	tpm._make_holder(emp)
	req = _new_submitted_request(emp, 100_000)
	pe = _create_funding_pe(req, 100_000)
	_sync_funding_fields(req)
	doc = frappe.get_doc("PM Request", req)
	frappe.db.commit()

	from erpnext_extensions.petty_management.services.request_action_policy import (
		compute_pm_request_action_flags,
	)

	flags = compute_pm_request_action_flags(doc)
	ctx = e2e_run_context()
	return {
		**ctx,
		"pm_request": req,
		"payment_entry": pe,
		"remaining_to_pay": float(getattr(doc, "remaining_to_pay", None) or 0),
		"total_paid_amount": float(doc.total_paid_amount or 0),
		"payment_status": doc.payment_status,
		"workflow_state": doc.workflow_state,
		"user": user,
		"flags": {
			"can_view_payment_entries": bool(flags.get("can_view_payment_entries")),
			"can_create_payment_entry": bool(flags.get("can_create_payment_entry")),
			"can_reject": bool(flags.get("can_reject")),
		},
	}
