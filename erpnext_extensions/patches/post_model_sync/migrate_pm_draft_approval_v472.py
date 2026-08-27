# Copyright (c) 2026, ERPNext Extensions contributors
"""v4.7.2: Draft approval until final Finance submit (Pending* stay docstatus=0).

Hard cutover: aborts if any in-flight Pending* Request/Clearance exist.
No grandfather, no permanent flags, no legacy branches.
"""

from __future__ import annotations

import json

import frappe
from frappe import _

from erpnext_extensions.patches.post_model_sync.migrate_pm_workflow_v402 import (
	_bulk_apply_pending_assignments,
	_rebuild_pm_clearance_workflow,
	_rebuild_pm_request_workflow,
	_seed_assignment_rules,
	_wf,
)
from erpnext_extensions.petty_management.services.workflow_utils import realign_doctype_workflow_states

REQUEST_PENDING_TITLES = (
	"Pending Manager Approval",
	"Pending CEO Approval",
	"Pending Finance Approval",
)
CLEARANCE_PENDING_TITLES = (
	"Pending Manager Approval",
	"Pending Finance Review",
)


def _workflow_state_names_for_titles(titles: tuple[str, ...]) -> list[str]:
	names: list[str] = []
	for title in titles:
		link = _wf(title)
		if link and link not in names:
			names.append(link)
		# Also match rows stored as the display title itself
		if title not in names:
			names.append(title)
	return names


def count_in_flight_pending_pm_docs() -> dict:
	"""Count Pending* PM Request / PM Clearance (any docstatus)."""
	req_states = _workflow_state_names_for_titles(REQUEST_PENDING_TITLES)
	clr_states = _workflow_state_names_for_titles(CLEARANCE_PENDING_TITLES)

	req_names: list[str] = []
	clr_names: list[str] = []
	if frappe.db.has_table("PM Request"):
		req_names = frappe.get_all(
			"PM Request",
			filters={"workflow_state": ("in", req_states)},
			pluck="name",
			order_by="modified desc",
		)
	if frappe.db.has_table("PM Clearance"):
		clr_names = frappe.get_all(
			"PM Clearance",
			filters={"workflow_state": ("in", clr_states)},
			pluck="name",
			order_by="modified desc",
		)
	return {
		"request_count": len(req_names),
		"clearance_count": len(clr_names),
		"request_names": req_names,
		"clearance_names": clr_names,
	}


def assert_no_in_flight_pending_pm_docs() -> None:
	"""Abort cutover when any Pending* docs exist (before workflow rebuild)."""
	stats = count_in_flight_pending_pm_docs()
	req_n = stats["request_count"]
	clr_n = stats["clearance_count"]
	if req_n == 0 and clr_n == 0:
		return

	def _sample(names: list[str], limit: int = 20) -> str:
		shown = names[:limit]
		extra = len(names) - len(shown)
		text = ", ".join(shown) if shown else "—"
		if extra > 0:
			text += _(" … and {0} more").format(extra)
		return text

	frappe.throw(
		_(
			"Cannot migrate to v4.7.2 Draft Approval: {0} PM Request(s) and {1} PM Clearance(s) "
			"are still in Pending* workflow states. Finish, return, or clear them first.\n\n"
			"PM Request ({0}): {2}\n"
			"PM Clearance ({1}): {3}"
		).format(req_n, clr_n, _sample(stats["request_names"]), _sample(stats["clearance_names"])),
		title=_("In-flight Pending documents"),
	)


def execute():
	frappe.flags.in_patch = True
	report: dict = {"aborted": False, "assignment_rules": [], "bulk_apply": {}}
	try:
		assert_no_in_flight_pending_pm_docs()
		_rebuild_pm_request_workflow()
		_rebuild_pm_clearance_workflow()
		realign_doctype_workflow_states("PM Request")
		realign_doctype_workflow_states("PM Clearance")
		report["assignment_rules"] = _seed_assignment_rules()
		# Bulk-apply while still inside the patch transaction (Frappe commits after Patch Log).
		report["bulk_apply"] = _bulk_apply_pending_assignments()
	except Exception:
		report["aborted"] = True
		frappe.flags.in_patch = False
		frappe.cache().set_value("pm_draft_approval_v472_migration_report", report)
		raise
	finally:
		frappe.flags.in_patch = False

	frappe.cache().set_value("pm_draft_approval_v472_migration_report", report)
	print(json.dumps({"pm_draft_approval_v472": report}, indent=2, default=str))
