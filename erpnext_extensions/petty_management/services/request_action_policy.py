"""PM Request Desk/workflow action rules (single source of truth for UI flags)."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt

from erpnext_extensions.petty_management.services.funding_queries import (
	has_draft_payment_entry,
	list_payment_entries_for_pm_request,
	sum_draft_pe_amount,
	sum_submitted_pe_amount,
)
from erpnext_extensions.petty_management.services.funding_service import close_pm_request_action_flags
from erpnext_extensions.petty_management.services.request_service import (
	request_ready_for_payment_entry,
	workflow_state_title,
)
from erpnext_extensions.petty_management.services.workflow_utils import get_allowed_workflow_actions

_EPS = 1e-6

MSG_CLOSE_DRAFT_PE = _("Cannot close while draft Payment Entries exist.")


def validate_pm_request_workflow_action(doc: Document, action: str) -> None:
	action = (action or "").strip()
	if action != "PM Reject":
		return
	if sum_submitted_pe_amount(doc.name) > _EPS:
		frappe.throw(
			_("Cannot reject PM Request while submitted Payment Entries exist. Cancel submitted Payment Entries first."),
			title=_("Reject not allowed"),
		)


def pm_request_has_submitted_funding(pm_request: str) -> bool:
	return sum_submitted_pe_amount(pm_request) > _EPS


def compute_pm_request_action_flags(doc: Document) -> dict:
	"""All toolbar / workflow visibility rules for PM Request."""
	can_create, create_block_reason = request_ready_for_payment_entry(doc)
	can_close, close_block_reason = close_pm_request_action_flags(doc)

	transitions = get_allowed_workflow_actions(doc)
	actions = [t.get("action") for t in transitions if t.get("action")]
	can_reject_wf = "PM Reject" in actions
	reject_block_reason = ""
	if can_reject_wf and pm_request_has_submitted_funding(doc.name):
		can_reject_wf = False
		reject_block_reason = _(
			"Reject is not allowed while submitted Payment Entries exist. Cancel submitted Payment Entries first."
		)

	submitted = sum_submitted_pe_amount(doc.name)
	draft = sum_draft_pe_amount(doc.name)
	remaining = flt(getattr(doc, "remaining_to_pay", None))
	if remaining <= 0 and submitted > 0:
		remaining = max(0.0, flt(doc.total_requested_amount) - submitted)

	ui_messages: list[str] = []
	if cint(getattr(doc, "is_closed", 0)):
		ui_messages.append(
			_("This PM Request is closed. Funding is frozen; clearance uses available balance only.")
		)
	elif not can_close and close_block_reason:
		ui_messages.append(str(close_block_reason))
	elif (
		not can_create
		and create_block_reason
		and workflow_state_title(doc) == "Approved"
		and not cint(getattr(doc, "is_closed", 0))
	):
		ui_messages.append(str(create_block_reason))
	if (
		not can_reject_wf
		and reject_block_reason
		and workflow_state_title(doc) == "Approved"
	):
		ui_messages.append(str(reject_block_reason))

	return {
		"can_create_payment_entry": bool(can_create),
		"create_block_reason": create_block_reason or "",
		"can_open_payment_entry": bool(doc.payment_entry),
		"can_close_pm_request": bool(can_close),
		"close_block_reason": close_block_reason or "",
		"can_reject": bool(can_reject_wf),
		"reject_block_reason": reject_block_reason or "",
		"ui_messages": ui_messages,
		"workflow_state_title": workflow_state_title(doc),
		"workflow_state": doc.workflow_state,
		"payment_status": doc.payment_status or "",
		"total_paid_amount": flt(getattr(doc, "total_paid_amount", None) or submitted),
		"remaining_to_pay": remaining,
		"total_draft_pe_amount": flt(getattr(doc, "total_draft_pe_amount", None) or draft),
		"is_closed": cint(getattr(doc, "is_closed", 0)),
		"allowed_workflow_actions": actions,
		"payment_entries": list_payment_entries_for_pm_request(doc.name),
	}

