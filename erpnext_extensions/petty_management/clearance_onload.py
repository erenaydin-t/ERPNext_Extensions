"""PM Clearance onload: repair stale status/workflow vs accounting (list/form consistency)."""

from __future__ import annotations

import frappe
from frappe.model.document import Document

from erpnext_extensions.petty_management.services.clearance_action_policy import (
	compute_lifecycle_status,
	sync_clearance_lifecycle,
)


def sync_pm_clearance_on_load(doc: Document, method=None) -> None:
	if not doc or not getattr(doc, "name", None):
		return
	if doc.doctype != "PM Clearance":
		return

	computed = compute_lifecycle_status(doc)
	stored_status = (frappe.db.get_value("PM Clearance", doc.name, "status") or "").strip()
	stored_ws = frappe.db.get_value("PM Clearance", doc.name, "workflow_state")

	je = (doc.journal_entry or "").strip()
	je_ds = None
	if je and frappe.db.exists("Journal Entry", je):
		from frappe.utils import cint

		je_ds = cint(frappe.db.get_value("Journal Entry", je, "docstatus"))

	needs_sync = stored_status != computed
	if not needs_sync and computed in ("Settled", "Pending Journal Entry Submission"):
		# Workflow link must match lifecycle for list/form (avoid Approved + Settled split-brain).
		from erpnext_extensions.petty_management.services.clearance_action_policy import (
			workflow_state_link_for_lifecycle,
		)

		expected_ws = workflow_state_link_for_lifecycle(computed)
		if expected_ws and stored_ws != expected_ws:
			needs_sync = True

	if needs_sync:
		sync_clearance_lifecycle(doc, persist=True)
		doc.status = frappe.db.get_value("PM Clearance", doc.name, "status")
		doc.workflow_state = frappe.db.get_value("PM Clearance", doc.name, "workflow_state")
