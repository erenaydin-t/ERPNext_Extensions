"""Workflow integration for Petty Management."""

from __future__ import annotations

import frappe
from frappe.model.workflow import apply_workflow as _apply_workflow


@frappe.whitelist()
def apply_workflow(doc, action):
	"""Guard PM workflow actions before standard apply; sync business status after.

	Also runs consecutive same-user Approve auto-skip (v4.1.4) so Desk and API
	share one path. Payment Entry must never call this.
	"""
	payload = frappe.parse_json(doc) if isinstance(doc, str) else doc
	if isinstance(payload, dict) and payload.get("doctype") == "PM Clearance" and payload.get("name"):
		from erpnext_extensions.petty_management.services.clearance_action_policy import (
			validate_apply_workflow_action,
		)

		cl_doc = frappe.get_doc("PM Clearance", payload["name"])
		validate_apply_workflow_action(cl_doc, action)

	if isinstance(payload, dict) and payload.get("doctype") == "PM Request" and payload.get("name"):
		from erpnext_extensions.petty_management.services.request_action_policy import (
			validate_pm_request_workflow_action,
		)
		from erpnext_extensions.petty_management.services.request_api_guard import get_pm_request_doc_for_read

		req_doc = get_pm_request_doc_for_read(payload["name"])
		validate_pm_request_workflow_action(req_doc, action)

	result = _apply_workflow(doc, action)

	from erpnext_extensions.petty_management.services.clearance_finance_review import (
		CLEARANCE_FINANCE_WORKFLOW_ACTIONS,
		stamp_clearance_finance_approver_after_act,
	)

	doctype = getattr(result, "doctype", None) or (result.get("doctype") if isinstance(result, dict) else None)
	name = getattr(result, "name", None) or (result.get("name") if isinstance(result, dict) else None)
	action_s = (action or "").strip()
	if doctype == "PM Clearance" and action_s in CLEARANCE_FINANCE_WORKFLOW_ACTIONS:
		doc_obj = result if hasattr(result, "reload") else frappe.get_doc(doctype, name)
		stamp_clearance_finance_approver_after_act(doc_obj, action_s)

	from erpnext_extensions.petty_management.services.auto_skip_approvals import (
		PM_AUTO_SKIP_APPROVE_ACTIONS,
		apply_consecutive_auto_approvals,
		refresh_pm_assignment_rules,
	)

	doctype = getattr(result, "doctype", None) or (result.get("doctype") if isinstance(result, dict) else None)
	name = getattr(result, "name", None) or (result.get("name") if isinstance(result, dict) else None)
	action_s = (action or "").strip()
	if (
		doctype in ("PM Request", "PM Clearance")
		and name
		and action_s in PM_AUTO_SKIP_APPROVE_ACTIONS
	):
		doc_obj = result if hasattr(result, "reload") else frappe.get_doc(doctype, name)
		refresh_pm_assignment_rules(doc_obj)
		doc_obj = apply_consecutive_auto_approvals(doc_obj)
		result = doc_obj

	_sync_business_status_after_workflow(result)
	return result


def _sync_business_status_after_workflow(result) -> None:
	"""Submitted workflow saves may skip validate; persist status from workflow/JE facts."""
	if not result:
		return
	doctype = getattr(result, "doctype", None) or (result.get("doctype") if isinstance(result, dict) else None)
	name = getattr(result, "name", None) or (result.get("name") if isinstance(result, dict) else None)
	if not doctype or not name:
		return
	if doctype == "PM Request":
		from erpnext_extensions.petty_management.services.business_status_service import (
			sync_pm_request_business_status,
		)

		doc = frappe.get_doc(doctype, name)
		status = sync_pm_request_business_status(doc)
		frappe.db.set_value(doctype, name, "status", status, update_modified=False)
		if hasattr(result, "status"):
			result.status = status
	elif doctype == "PM Clearance":
		from erpnext_extensions.petty_management.services.business_status_service import (
			sync_pm_clearance_business_status,
		)

		doc = frappe.get_doc(doctype, name)
		sync_pm_clearance_business_status(doc, persist=True)
		if hasattr(result, "status"):
			result.status = doc.status
