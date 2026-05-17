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

	return _apply_workflow(doc, action)
