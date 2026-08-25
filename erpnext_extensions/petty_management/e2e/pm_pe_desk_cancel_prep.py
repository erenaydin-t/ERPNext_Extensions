# Copyright (c) 2026, Farbod Siyahpoosh and contributors
"""Prepare a submitted Payment Entry linked to PM Request for Desk cancel E2E."""

from __future__ import annotations

import frappe
from frappe.utils import flt

from erpnext_extensions.petty_management.tests import test_pm_clearance as tpm
from erpnext_extensions.petty_management.tests.test_pm_request_multi_pe import (
	_create_funding_pe,
	_ensure_pm_settings_bank,
	_new_submitted_request,
	_sync_funding_fields,
)


@frappe.whitelist()
def prepare_single_submitted_pe_for_desk_cancel() -> dict:
	"""Fully paid Request + one submitted PE (no Clearance) — Desk cancel should succeed."""
	frappe.set_user("Administrator")
	tpm._ensure_company_context()
	tpm._ensure_petty_account()
	_ensure_pm_settings_bank()
	emp = tpm._make_employee()
	tpm._make_holder(emp)
	req = _new_submitted_request(emp, 25_000)
	ws = frappe.db.get_value("PM Request", req, "workflow_state")
	pe = _create_funding_pe(req, 25_000)
	_sync_funding_fields(req)
	doc = frappe.get_doc("PM Request", req)
	frappe.db.commit()
	return {
		"pm_request": req,
		"payment_entry": pe,
		"workflow_state": ws,
		"payment_status": doc.payment_status,
		"status": doc.status,
		"total_paid_amount": flt(doc.total_paid_amount),
		"docstatus": doc.docstatus,
	}
