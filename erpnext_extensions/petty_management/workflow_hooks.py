"""Workflow integration for Petty Management."""

from __future__ import annotations

import frappe
from frappe.model.workflow import apply_workflow as _apply_workflow


@frappe.whitelist()
def apply_workflow(doc, action):
	"""Guard PM Clearance workflow actions before standard apply."""
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

	return _apply_workflow(doc, action)
