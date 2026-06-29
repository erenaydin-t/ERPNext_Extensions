"""PM Request Desk/workflow action rules (single source of truth for UI flags)."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt

from erpnext_extensions.petty_management.services.funding_queries import (
	count_payment_entries_for_pm_request,
	has_draft_payment_entry,
	list_payment_entries_for_pm_request,
	payment_entry_list_filters_for_pm_request,
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

MSG_CLOSED_FROZEN = _(
	"This PM Request is closed. Funding is frozen; clearance uses available balance only."
)
MSG_SUBMIT_FIRST = _("Submit the PM Request first.")


def _unique_ui_messages(*parts: str) -> list[str]:
	seen: set[str] = set()
	out: list[str] = []
	for part in parts:
		text = (part or "").strip()
		if not text or text in seen:
			continue
		seen.add(text)
		out.append(text)
	return out


def build_pm_request_ui_messages(
	doc: Document,
	*,
	can_create: bool,
	create_block_reason: str,
	can_close: bool,
	close_block_reason: str,
	can_reject_wf: bool,
	reject_block_reason: str,
) -> list[str]:
	"""Single source for Desk intro banners (deduplicated, priority-ordered)."""
	if cint(getattr(doc, "is_closed", 0)):
		return [str(MSG_CLOSED_FROZEN)]

	if doc.docstatus != 1:
		return [str(MSG_SUBMIT_FIRST)]

	parts: list[str] = []
	ws = workflow_state_title(doc)
	if not can_close and close_block_reason:
		parts.append(str(close_block_reason))
	if (
		not can_create
		and create_block_reason
		and ws == "Approved"
	):
		parts.append(str(create_block_reason))
	if not can_reject_wf and reject_block_reason and ws == "Approved":
		parts.append(str(reject_block_reason))
	return _unique_ui_messages(*parts)


def validate_pm_request_workflow_action(doc: Document, action: str) -> None:
	action = (action or "").strip()
	if action != "PM Reject":
		return
	if count_payment_entries_for_pm_request(doc.name)["submitted_payment_entry_count"] > 0:
		frappe.throw(
			_("Cannot reject PM Request while submitted Payment Entries exist. Cancel submitted Payment Entries first."),
			title=_("Reject not allowed"),
		)
	if sum_submitted_pe_amount(doc.name) > _EPS:
		frappe.throw(
			_("Cannot reject PM Request while submitted Payment Entries exist. Cancel submitted Payment Entries first."),
			title=_("Reject not allowed"),
		)


def pm_request_has_submitted_funding(pm_request: str) -> bool:
	counts = count_payment_entries_for_pm_request(pm_request)
	if counts.get("submitted_payment_entry_count", 0) > 0:
		return True
	return sum_submitted_pe_amount(pm_request) > _EPS


def compute_pm_request_action_flags(doc: Document) -> dict:
	"""All toolbar / workflow visibility rules for PM Request."""
	if doc.name and doc.docstatus == 1:
		from erpnext_extensions.petty_management.services.funding_service import sync_pm_request_funding_fields

		sync_pm_request_funding_fields(doc)

	can_create, create_block_reason = request_ready_for_payment_entry(doc)
	can_close, close_block_reason = close_pm_request_action_flags(doc)

	transitions = get_allowed_workflow_actions(doc)
	actions = [t.get("action") for t in transitions if t.get("action")]
	pe_counts = count_payment_entries_for_pm_request(doc.name)
	submitted_pe_count = pe_counts["submitted_payment_entry_count"]
	draft_pe_count = pe_counts["draft_payment_entry_count"]
	payment_entry_count = pe_counts["payment_entry_count"]
	is_closed = cint(getattr(doc, "is_closed", 0))

	can_reject_wf = (
		"PM Reject" in actions
		and not is_closed
		and submitted_pe_count == 0
		and flt(getattr(doc, "total_paid_amount", 0)) <= _EPS
	)
	reject_block_reason = ""
	if "PM Reject" in actions and not can_reject_wf and not is_closed and (
		submitted_pe_count > 0 or flt(getattr(doc, "total_paid_amount", 0)) > _EPS
	):
		reject_block_reason = _(
			"Reject is not allowed while submitted Payment Entries exist. Cancel submitted Payment Entries first."
		)
	elif "PM Reject" in actions and is_closed:
		can_reject_wf = False

	submitted = sum_submitted_pe_amount(doc.name)
	draft = sum_draft_pe_amount(doc.name)
	remaining = flt(getattr(doc, "remaining_to_pay", None))
	if remaining <= 0 and submitted > 0:
		remaining = max(0.0, flt(doc.total_requested_amount) - submitted)

	ui_messages = build_pm_request_ui_messages(
		doc,
		can_create=can_create,
		create_block_reason=create_block_reason or "",
		can_close=can_close,
		close_block_reason=close_block_reason or "",
		can_reject_wf=can_reject_wf,
		reject_block_reason=reject_block_reason or "",
	)

	return {
		"can_create_payment_entry": bool(can_create),
		"create_block_reason": create_block_reason or "",
		"can_view_payment_entries": payment_entry_count > 0,
		"can_open_payment_entry": False,
		"can_close_pm_request": bool(can_close),
		"close_block_reason": close_block_reason or "",
		"can_reject": bool(can_reject_wf),
		"reject_block_reason": reject_block_reason or "",
		"submitted_payment_entry_count": submitted_pe_count,
		"draft_payment_entry_count": draft_pe_count,
		"payment_entry_count": payment_entry_count,
		"payment_entry_list_filters": payment_entry_list_filters_for_pm_request(doc.name),
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

