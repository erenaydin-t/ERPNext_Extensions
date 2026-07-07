"""Remove Cancel Cheque workflow actions from PDC Workflow (use Rollback instead)."""

from __future__ import annotations

import frappe


def execute():
	_remove_cancel_workflow_transitions()
	backfill_opening_import_workflow_state()


def _remove_cancel_workflow_transitions():
	workflow = frappe.db.get_value("Workflow", {"document_type": "Post Dated Cheque"}, "name")
	if not workflow:
		return
	for action in ("Cancel Cheque", "Cancel Issued Payable"):
		frappe.db.delete(
			"Workflow Transition",
			{
				"parent": workflow,
				"action": action,
			},
		)
	frappe.db.commit()


def backfill_opening_import_workflow_state():
	"""Set opening_import_workflow_state on legacy opening-import PDCs."""
	from erpnext_extensions.cheque_management.pdc_opening_import_baseline import (
		infer_opening_import_baseline_state,
	)

	for row in frappe.get_all(
		"Post Dated Cheque",
		filters={"is_opening_import": 1, "opening_import_workflow_state": ["in", ["", None]]},
		fields=["name"],
	):
		doc = frappe.get_doc("Post Dated Cheque", row.name)
		baseline = infer_opening_import_baseline_state(doc)
		frappe.db.set_value(
			"Post Dated Cheque",
			row.name,
			"opening_import_workflow_state",
			baseline,
			update_modified=False,
		)
	frappe.db.commit()
