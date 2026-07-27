# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

"""Ensure Debt Purchase Workflow States / Actions / PDC Workflow transitions exist."""

from __future__ import annotations

import frappe


def execute():
	for name, style in (
		("Assigned to Bank for Debt Purchase", "Info"),
		("Debt Purchase Settled", "Success"),
	):
		if not frappe.db.exists("Workflow State", name):
			frappe.get_doc(
				{
					"doctype": "Workflow State",
					"workflow_state_name": name,
					"style": style,
				}
			).insert(ignore_permissions=True)

	for name in ("Assign for Debt Purchase", "Return Debt Purchase Cheque"):
		if not frappe.db.exists("Workflow Action Master", name):
			frappe.get_doc(
				{
					"doctype": "Workflow Action Master",
					"workflow_action_name": name,
				}
			).insert(ignore_permissions=True)

	if not frappe.db.exists("Workflow", "PDC Workflow"):
		return

	doc = frappe.get_doc("Workflow", "PDC Workflow")
	changed = False
	existing_states = {s.state for s in doc.states}
	for state in ("Assigned to Bank for Debt Purchase", "Debt Purchase Settled"):
		if state not in existing_states:
			doc.append(
				"states",
				{
					"state": state,
					"doc_status": "1",
					"allow_edit": "All",
				},
			)
			changed = True

	existing_tr = {(t.state, t.next_state, t.action) for t in doc.transitions}
	wanted = [
		(
			"Registered",
			"Assigned to Bank for Debt Purchase",
			"Assign for Debt Purchase",
			"doc.get('cheque_direction') == 'Receivable'",
		),
		(
			"Assigned to Bank for Debt Purchase",
			"Returned",
			"Return Debt Purchase Cheque",
			"doc.get('cheque_direction') == 'Receivable'",
		),
	]
	for state, next_state, action, condition in wanted:
		key = (state, next_state, action)
		if key not in existing_tr:
			doc.append(
				"transitions",
				{
					"state": state,
					"action": action,
					"next_state": next_state,
					"allowed": "All",
					"allow_self_approval": 1,
					"condition": condition,
				},
			)
			changed = True

	if changed:
		doc.save(ignore_permissions=True)
