# Copyright (c) 2026, ERPNext Extensions contributors
"""v4.5.3: PM Clearance Finance Review role queue (native Workflow Action).

Idempotent migration:
- Role + DocPerm
- PM Settings default
- Grant legacy finance_supervisor user the review role
- Disable Based-on-Field Finance Assignment Rule
- Rebuild Clearance finance workflow transitions (role queue)
- Cut over in-flight Pending Finance Review docs (preserve historical stamps on terminal docs)
"""

from __future__ import annotations

import frappe
from frappe.utils import cint

from erpnext_extensions.petty_management.services.clearance_finance_review import (
	DEFAULT_CLEARANCE_FINANCE_REVIEW_ROLE,
	get_clearance_finance_review_role,
)
from erpnext_extensions.patches.post_model_sync.migrate_pm_workflow_v402 import (
	_rebuild_pm_clearance_workflow,
	_wf,
)

FINANCE_ASSIGNMENT_RULE = "PM Clearance Finance Review"


def _ensure_role(role_name: str) -> None:
	if frappe.db.exists("Role", role_name):
		return
	doc = frappe.new_doc("Role")
	doc.role_name = role_name
	doc.desk_access = 1
	doc.insert(ignore_permissions=True)


def _sync_clearance_reviewer_docperm() -> None:
	"""Add reviewer DocPerm on PM Clearance (never Custom DocPerm — it replaces all standard perms)."""
	frappe.db.delete("Custom DocPerm", {"parent": "PM Clearance"})
	role = get_clearance_finance_review_role()
	dt = frappe.get_doc("DocType", "PM Clearance")
	found = False
	for p in dt.permissions:
		if p.role == role:
			p.read = 1
			p.write = 1
			p.submit = 1
			p.report = 1
			found = True
			break
	if not found:
		dt.append("permissions", {"role": role, "read": 1, "write": 1, "submit": 1, "report": 1})
	dt.save(ignore_permissions=True)
	frappe.clear_cache(doctype="PM Clearance")


def _default_pm_settings_role() -> None:
	if not frappe.db.exists("DocType", "PM Settings"):
		return
	meta = frappe.get_meta("PM Settings")
	if not meta.has_field("clearance_finance_review_role"):
		return
	settings = frappe.get_single("PM Settings")
	current = getattr(settings, "clearance_finance_review_role", None)
	if not (isinstance(current, str) and current.strip()):
		settings.db_set(
			"clearance_finance_review_role",
			DEFAULT_CLEARANCE_FINANCE_REVIEW_ROLE,
			update_modified=False,
		)


def _grant_legacy_finance_supervisor_reviewer_role() -> None:
	settings = frappe.get_single("PM Settings")
	supervisor = getattr(settings, "finance_supervisor", None)
	if not supervisor or not frappe.db.exists("User", supervisor):
		return
	if not frappe.db.get_value("User", supervisor, "enabled"):
		return
	role = get_clearance_finance_review_role()
	user = frappe.get_doc("User", supervisor)
	have = {r.role for r in user.roles}
	if role not in have:
		user.append("roles", {"role": role})
		user.save(ignore_permissions=True)


def _disable_clearance_finance_assignment_rule() -> None:
	if not frappe.db.exists("Assignment Rule", FINANCE_ASSIGNMENT_RULE):
		return
	frappe.db.set_value("Assignment Rule", FINANCE_ASSIGNMENT_RULE, "disabled", 1, update_modified=False)


def _close_clearance_finance_todos(cl_name: str) -> None:
	for row in frappe.get_all(
		"ToDo",
		filters={
			"reference_type": "PM Clearance",
			"reference_name": cl_name,
			"status": "Open",
			"assignment_rule": FINANCE_ASSIGNMENT_RULE,
		},
		pluck="name",
	):
		todo = frappe.get_doc("ToDo", row)
		todo.status = "Closed"
		todo.save(ignore_permissions=True)


def _cutover_pending_finance_clearances() -> dict:
	"""Hard cutover in-flight Pending Finance Review to role queue."""
	from frappe.workflow.doctype.workflow_action.workflow_action import (
		clear_workflow_actions,
		process_workflow_actions,
	)

	pending_fin = _wf("Pending Finance Review")
	report = {"cutover": 0, "todos_closed": 0}
	if not pending_fin:
		return report

	for row in frappe.get_all(
		"PM Clearance",
		filters={"workflow_state": pending_fin, "docstatus": 1},
		fields=["name", "finance_approver"],
	):
		name = row.name
		frappe.db.set_value("PM Clearance", name, "finance_approver", None, update_modified=False)
		_close_clearance_finance_todos(name)
		report["todos_closed"] += 1
		clear_workflow_actions("PM Clearance", name)
		doc = frappe.get_doc("PM Clearance", name)
		process_workflow_actions(doc, "on_update")
		report["cutover"] += 1
	return report


def execute():
	frappe.flags.in_migrate = True
	try:
		_ensure_role(DEFAULT_CLEARANCE_FINANCE_REVIEW_ROLE)
		_default_pm_settings_role()
		_sync_clearance_reviewer_docperm()
		_grant_legacy_finance_supervisor_reviewer_role()
		_disable_clearance_finance_assignment_rule()
		_rebuild_pm_clearance_workflow()
		report = _cutover_pending_finance_clearances()
		frappe.db.commit()
		frappe.logger("petty_management").info("PM v4.5.3 clearance finance role queue: %s", report)
	finally:
		frappe.flags.in_migrate = False
