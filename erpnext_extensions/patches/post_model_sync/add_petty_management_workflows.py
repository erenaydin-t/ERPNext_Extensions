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
	_wf_state("Paid")

	w = frappe.new_doc("Workflow")
	w.workflow_name = "PM Request Workflow"
	w.document_type = "PM Request"
	w.is_active = 1
	w.workflow_state_field = "workflow_state"
	for state, doc_status in (
		("Draft", "0"),
		("Pending Approval", "1"),
		("Approved", "1"),
		("Paid", "1"),
		("Rejected", "0"),
	):
		w.append(
			"states",
			{"state": state, "doc_status": doc_status, "allow_edit": "All"},
		)
	transitions = (
		("Draft", "PM Submit for Approval", "Pending Approval", "Petty Management User"),
		("Pending Approval", "PM Approve", "Approved", "Petty Management Manager"),
		("Pending Approval", "PM Reject", "Rejected", "Petty Management Manager"),
		("Approved", "PM Mark Paid", "Paid", "Petty Management Accountant"),
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


def _ensure_pm_clearance_workflow():
	if frappe.db.exists("Workflow", "PM Clearance Workflow"):
		return
	_wf_state("Pending Finance Review")
	_wf_state("Posted")

	w = frappe.new_doc("Workflow")
	w.workflow_name = "PM Clearance Workflow"
	w.document_type = "PM Clearance"
	w.is_active = 1
	w.workflow_state_field = "workflow_state"
	# DocStatus 1 while in review/approval matches submittable petty clearance flow.
	for state, doc_status in (
		("Draft", "0"),
		("Pending Finance Review", "1"),
		("Approved", "1"),
		("Posted", "1"),
		("Rejected", "0"),
	):
		w.append(
			"states",
			{"state": state, "doc_status": doc_status, "allow_edit": "All"},
		)
	transitions = (
		("Draft", "PM Submit Finance Review", "Pending Finance Review", "Petty Management User"),
		("Pending Finance Review", "PM Approve", "Approved", "Petty Management Manager"),
		("Pending Finance Review", "PM Reject", "Rejected", "Petty Management Manager"),
		("Approved", "PM Post", "Posted", "Petty Management Accountant"),
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


def execute():
	_ensure_pm_request_workflow()
	_ensure_pm_clearance_workflow()
	frappe.clear_cache(doctype="Workflow")
