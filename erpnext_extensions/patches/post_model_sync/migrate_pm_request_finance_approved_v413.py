# Copyright (c) 2026, ERPNext Extensions contributors
"""v4.1.3 Option A: PM Request terminal workflow = Finance Approved (idempotent)."""

from __future__ import annotations

import frappe

from erpnext_extensions.patches.post_model_sync.migrate_pm_workflow_v402 import (
	_migrate_pm_request_docs,
	_rebuild_pm_request_workflow,
	_seed_assignment_rules,
	_wf,
)
from erpnext_extensions.petty_management.services.business_status_service import (
	REQ_WORKFLOW_FINANCE_APPROVED,
	sync_pm_request_business_status,
)
from erpnext_extensions.petty_management.services.workflow_utils import realign_doctype_workflow_states


def execute():
	if not frappe.db.exists("DocType", "PM Request"):
		return

	_wf(REQ_WORKFLOW_FINANCE_APPROVED)
	_wf("Waiting for Payment")  # keep master for any leftover link values
	_rebuild_pm_request_workflow()
	_seed_assignment_rules()
	realign_doctype_workflow_states("PM Request")

	# Remap legacy Waiting for Payment / Approved → Finance Approved (preserves payment fields)
	report = _migrate_pm_request_docs()

	# Re-sync business status for finance-cleared docs without touching amounts / payment_status
	finance = _wf(REQ_WORKFLOW_FINANCE_APPROVED)
	for name in frappe.get_all(
		"PM Request",
		filters={"workflow_state": finance},
		pluck="name",
	):
		doc = frappe.get_doc("PM Request", name)
		old_status = doc.status
		new_status = sync_pm_request_business_status(doc)
		if new_status != old_status:
			frappe.db.set_value("PM Request", name, "status", new_status, update_modified=False)

	frappe.clear_cache(doctype="PM Request")
	frappe.db.commit()
	frappe.logger("erpnext_extensions").info(
		f"migrate_pm_request_finance_approved_v413: {report}"
	)
