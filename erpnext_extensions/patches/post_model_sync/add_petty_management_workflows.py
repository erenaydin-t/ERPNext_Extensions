from __future__ import annotations

import frappe

from erpnext_extensions.petty_management.services.workflow_utils import (
	normalize_workflow_definition,
	realign_doctype_workflow_states,
	resolve_workflow_state_link,
)


def _wf_state(name: str) -> str:
	"""Return Workflow State name (document name)."""
	return resolve_workflow_state_link(name) or name


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
			{"state": _wf_state(state), "doc_status": doc_status, "allow_edit": "All"},
		)
	transitions = (
		("Draft", "PM Submit for Approval", "Pending Approval", "Petty Management User"),
		("Pending Approval", "PM Approve", "Approved", "Petty Management User"),
		("Pending Approval", "PM Reject", "Rejected", "Petty Management User"),
		("Approved", "PM Reject", "Rejected", "Petty Management User"),
	)
	for state, action, next_state, role in transitions:
		w.append(
			"transitions",
			{
				"state": _wf_state(state),
				"action": action,
				"next_state": _wf_state(next_state),
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

	still_refs_paid = any(getattr(t, "next_state", None) == "Paid" for t in w.transitions)
	if not still_refs_paid:
		for row in list(w.states):
			if row.state == "Paid":
				w.remove(row)
				changed = True

	if changed:
		w.save(ignore_permissions=True)
	_repair_workflow_common(name, "PM Request")


def _ensure_pm_clearance_workflow():
	if frappe.db.exists("Workflow", "PM Clearance Workflow"):
		return
	_wf_state("Pending Finance Review")
	_wf_state("Approved")
	_wf_state("Rejected")

	w = frappe.new_doc("Workflow")
	w.workflow_name = "PM Clearance Workflow"
	w.document_type = "PM Clearance"
	w.is_active = 1
	w.workflow_state_field = "workflow_state"
	for state, doc_status in (
		("Draft", "0"),
		("Pending Finance Review", "1"),
		("Approved", "1"),
		("Rejected", "1"),
	):
		w.append(
			"states",
			{"state": _wf_state(state), "doc_status": doc_status, "allow_edit": "All"},
		)
	transitions = (
		("Draft", "PM Submit Finance Review", "Pending Finance Review", "Petty Management User"),
		("Pending Finance Review", "PM Approve", "Approved", "Petty Management Accountant"),
		("Pending Finance Review", "PM Reject", "Rejected", "Petty Management Accountant"),
	)
	for state, action, next_state, role in transitions:
		w.append(
			"transitions",
			{
				"state": _wf_state(state),
				"action": action,
				"next_state": _wf_state(next_state),
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
		# Reject after approval is invalid once settlement exists; server also blocks via accounting lock.
		if row.state == "Approved" and row.action == "PM Reject":
			w.remove(row)
			changed = True
	for row in list(w.states):
		if row.state == "Posted":
			w.remove(row)
			changed = True
	accounting_states = (
		("Pending Journal Entry Submission", "1"),
		("Settled", "1"),
	)
	# v4.0.2: accounting titles are business status only — remove from Workflow if present.
	for row in list(w.states):
		title = frappe.db.get_value("Workflow State", row.state, "workflow_state_name") or row.state
		if title in ("Pending Journal Entry Submission", "Settled") or row.state in {
			_wf_state("Pending Journal Entry Submission"),
			_wf_state("Settled"),
			"Pending Journal Entry Submission",
			"Settled",
		}:
			w.remove(row)
			changed = True
	# Do not re-add accounting_states (removed intentionally).
	_ = accounting_states
	if changed:
		w.save(ignore_permissions=True)
	_repair_workflow_common(name, "PM Clearance")


def _repair_workflow_common(workflow_name: str, doctype: str) -> None:
	if not frappe.db.exists("Workflow", workflow_name):
		return
	w = frappe.get_doc("Workflow", workflow_name)
	changed = normalize_workflow_definition(w)
	if changed:
		w.save(ignore_permissions=True)
	realign_doctype_workflow_states(doctype)
	frappe.clear_cache(doctype="Workflow")


def repair_pm_request_workflow():
	"""Idempotent repair — delegates to v4.0.2 multi-level workflow migration."""
	from erpnext_extensions.patches.post_model_sync.migrate_pm_workflow_v402 import (
		execute as migrate_v402,
	)

	migrate_v402()


def repair_pm_clearance_workflow():
	"""Idempotent repair — delegates to v4.0.2 multi-level workflow migration."""
	from erpnext_extensions.patches.post_model_sync.migrate_pm_workflow_v402 import (
		execute as migrate_v402,
	)

	migrate_v402()


def execute():
	# Prefer v4.0.2 rebuild when available; fall back to create-if-missing for fresh installs.
	try:
		from erpnext_extensions.patches.post_model_sync.migrate_pm_workflow_v402 import (
			execute as migrate_v402,
		)

		migrate_v402()
	except Exception:
		_ensure_pm_request_workflow()
		_repair_pm_request_workflow()
		_ensure_pm_clearance_workflow()
		_repair_pm_clearance_workflow()
	frappe.clear_cache(doctype="Workflow")
	frappe.db.commit()
