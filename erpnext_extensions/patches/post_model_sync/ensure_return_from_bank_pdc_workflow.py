# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

"""Ensure Return from Bank Workflow Action and PDC Workflow transition exist."""

from __future__ import annotations

import frappe


def execute():
	action = "Return from Bank"
	if not frappe.db.exists("Workflow Action Master", action):
		frappe.get_doc(
			{
				"doctype": "Workflow Action Master",
				"workflow_action_name": action,
			}
		).insert(ignore_permissions=True)

	if not frappe.db.exists("Workflow", "PDC Workflow"):
		return

	doc = frappe.get_doc("Workflow", "PDC Workflow")
	existing = {(t.state, t.next_state, t.action) for t in doc.transitions}
	key = ("Sent to Bank", "Registered", action)
	if key in existing:
		return

	doc.append(
		"transitions",
		{
			"state": "Sent to Bank",
			"action": action,
			"next_state": "Registered",
			"allowed": "All",
			"allow_self_approval": 1,
			"condition": "doc.get('cheque_direction') == 'Receivable'",
		},
	)
	doc.save(ignore_permissions=True)
