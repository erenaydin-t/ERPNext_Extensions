from __future__ import annotations

import frappe


def _wf_state(name: str) -> str:
	"""Return Workflow State name (document name)."""
	if frappe.db.exists("Workflow State", name):
		return name
	doc = frappe.new_doc("Workflow State")
	doc.workflow_state_name = name
	doc.insert(ignore_permissions=True)
	return doc.name


def _ensure_pm_request_workflow():
	if frappe.db.exists("Workflow", "PM Request Workflow"):
		return
	_wf_state("Pending Approval")
	_wf_state("Approved")
	_wf_state("Rejected")

	w = frappe.new_doc("Workflow")
	w.workflow_name = "PM Request Workflow"
	w.document_type = "PM Request"
	w.is_active = 1
	w.workflow_state_field = "workflow_state"
	# Rejected must use doc_status 1: Frappe forbids transitions where doc_status goes 1 -> 0
	# (e.g. Pending Approval / Approved -> Rejected).
	# Payment is not a workflow step: use Create Payment Entry on the document (status → Paid there).
	for state, doc_status in (
		("Draft", "0"),
		("Pending Approval", "1"),
		("Approved", "1"),
		("Rejected", "1"),
	):
		w.append(
			"states",
			{"state": state, "doc_status": doc_status, "allow_edit": "All"},
		)
	transitions = (
		("Draft", "PM Submit for Approval", "Pending Approval", "Petty Management User"),
		("Pending Approval", "PM Approve", "Approved", "Petty Management Manager"),
		("Pending Approval", "PM Reject", "Rejected", "Petty Management Manager"),
		("Approved", "PM Reject", "Rejected", "Petty Management Manager"),
	)
	for state, action, next_state, role in transitions:
		w.append(
			"transitions",
			{
				"state": state,
				"action": action,
				"next_state": next_state,
				"allowed": role,
				"allow_self_approval": 1,
			},
		)
	w.insert(ignore_permissions=True)


def _repair_pm_request_workflow():
	"""Existing sites: drop PM Mark Paid transition; drop Paid state if unused. Payment is PE-only."""
	name = "PM Request Workflow"
	if not frappe.db.exists("Workflow", name):
		return
	w = frappe.get_doc("Workflow", name)
	changed = False
	for row in list(w.transitions):
		if row.action == "PM Mark Paid":
			w.remove(row)
			changed = True

	still_refs_paid = any(
		getattr(t, "next_state", None) == "Paid" for t in w.transitions
	)
	if not still_refs_paid:
		for row in list(w.states):
			if row.state == "Paid":
				w.remove(row)
				changed = True

	if changed:
		w.save(ignore_permissions=True)


def _ensure_pm_clearance_workflow():
	if frappe.db.exists("Workflow", "PM Clearance Workflow"):
		return
	_wf_state("Pending Finance Review")
	_wf_state("Approved")

	w = frappe.new_doc("Workflow")
	w.workflow_name = "PM Clearance Workflow"
	w.document_type = "PM Clearance"
	w.is_active = 1
	w.workflow_state_field = "workflow_state"
	# DocStatus 1 while in review/approval matches submittable petty clearance flow.
	# Rejected must use doc_status 1: see PM Request workflow note (no 1 -> 0 transitions).
	for state, doc_status in (
		("Draft", "0"),
		("Pending Finance Review", "1"),
		("Approved", "1"),
		("Rejected", "1"),
	):
		w.append(
			"states",
			{"state": state, "doc_status": doc_status, "allow_edit": "All"},
		)
	transitions = (
		("Draft", "PM Submit Finance Review", "Pending Finance Review", "Petty Management User"),
		("Pending Finance Review", "PM Approve", "Approved", "Petty Management Manager"),
		("Pending Finance Review", "PM Reject", "Rejected", "Petty Management Manager"),
		("Approved", "PM Reject", "Rejected", "Petty Management Manager"),
	)
	for state, action, next_state, role in transitions:
		w.append(
			"transitions",
			{
				"state": state,
				"action": action,
				"next_state": next_state,
				"allowed": role,
				"allow_self_approval": 1,
			},
		)
	w.insert(ignore_permissions=True)


def _repair_pm_clearance_workflow():
	"""Existing sites: remove Posted state/PM Post transition. Settlement is not a workflow step."""
	name = "PM Clearance Workflow"
	if not frappe.db.exists("Workflow", name):
		return
	w = frappe.get_doc("Workflow", name)
	changed = False
	for row in list(w.transitions):
		if row.action == "PM Post" or row.next_state == "Posted":
			w.remove(row)
			changed = True
	for row in list(w.states):
		if row.state == "Posted":
			w.remove(row)
			changed = True
	if changed:
		w.save(ignore_permissions=True)


def repair_pm_request_workflow():
	"""Idempotent repair for existing sites (also called from after_migrate)."""
	_repair_pm_request_workflow()


def repair_pm_clearance_workflow():
	"""Idempotent repair for existing sites (also called from after_migrate)."""
	_repair_pm_clearance_workflow()


def execute():
	_ensure_pm_request_workflow()
	_repair_pm_request_workflow()
	_ensure_pm_clearance_workflow()
	_repair_pm_clearance_workflow()
	frappe.clear_cache(doctype="Workflow")
	frappe.db.commit()
