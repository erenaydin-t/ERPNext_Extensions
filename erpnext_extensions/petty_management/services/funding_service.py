"""Sync PM Request funding aggregates, payment status, and operational close."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, now_datetime

from erpnext_extensions.petty_management.services.allocation_service import sum_prior_pm_request_allocations
from erpnext_extensions.petty_management.services.funding_queries import (
	has_draft_payment_entry,
	resolve_latest_payment_entry,
	sum_draft_pe_amount,
	sum_submitted_pe_amount,
)
from erpnext_extensions.petty_management.services.request_service import (
	sync_request_status_from_workflow,
	workflow_state_title,
)

_EPS = 1e-6

CLOSE_REASONS = (
	"Budget Limitation",
	"Partial Approval",
	"Cancelled by Requester",
	"Other",
)


def derive_payment_status_from_totals(doc: Document) -> None:
	requested = flt(doc.total_requested_amount)
	paid = flt(getattr(doc, "total_paid_amount", None))
	if paid <= _EPS:
		doc.payment_status = "Not Paid"
	elif paid + _EPS < requested:
		doc.payment_status = "Partially Paid"
	else:
		doc.payment_status = "Paid"


def sync_pm_request_funding_fields(pm_request: str | Document) -> None:
	from erpnext_extensions.petty_management.services.request_api_guard import get_pm_request_doc_internal

	doc = pm_request if isinstance(pm_request, Document) else get_pm_request_doc_internal(pm_request)
	submitted = sum_submitted_pe_amount(doc.name)
	draft = sum_draft_pe_amount(doc.name)
	requested = flt(doc.total_requested_amount)
	allocated = flt(sum_prior_pm_request_allocations(doc.name, None))
	remaining = max(0.0, requested - submitted)
	available = submitted - allocated

	doc.total_paid_amount = submitted
	doc.total_draft_pe_amount = draft
	doc.remaining_to_pay = remaining
	doc.allocated_amount = allocated
	doc.available_for_clearance = available
	derive_payment_status_from_totals(doc)
	latest = resolve_latest_payment_entry(doc.name)
	if latest:
		doc.payment_entry = latest
	sync_request_status_from_workflow(doc)
	frappe.db.set_value(
		"PM Request",
		doc.name,
		{
			"total_paid_amount": doc.total_paid_amount,
			"total_draft_pe_amount": doc.total_draft_pe_amount,
			"remaining_to_pay": doc.remaining_to_pay,
			"allocated_amount": doc.allocated_amount,
			"available_for_clearance": doc.available_for_clearance,
			"payment_status": doc.payment_status,
			"status": doc.status,
			"payment_entry": doc.payment_entry,
		},
		update_modified=False,
	)


def validate_new_pe_amount(pm_request: str, new_amount: float) -> None:
	from erpnext_extensions.petty_management.services.request_api_guard import get_pm_request_doc_for_read

	doc = get_pm_request_doc_for_read(pm_request)
	if cint(getattr(doc, "is_closed", 0)):
		frappe.throw(_("This PM Request is closed. Payment Entry cannot be created."), title=_("Closed"))
	submitted = sum_submitted_pe_amount(pm_request)
	draft = sum_draft_pe_amount(pm_request)
	requested = flt(doc.total_requested_amount)
	if submitted + draft + flt(new_amount) > requested + _EPS:
		frappe.throw(
			_("Payment amount exceeds remaining request balance (submitted {0}, draft {1}, requested {2}).").format(
				submitted, draft, requested
			),
			title=_("Over-funding"),
		)


def close_pm_request(
	pm_request: str,
	close_reason: str | None = None,
	close_reason_detail: str | None = None,
) -> None:
	from erpnext_extensions.petty_management.services.request_api_guard import get_pm_request_doc_for_write

	doc = get_pm_request_doc_for_write(pm_request)
	if doc.docstatus != 1:
		frappe.throw(_("Submit the PM Request before closing."))
	ws = workflow_state_title(doc)
	if ws == "Rejected" or (doc.status or "").strip() == "Rejected":
		frappe.throw(_("Rejected requests cannot be closed."))
	if ws != "Approved":
		frappe.throw(_("Close is only available for Approved PM Requests."))
	if cint(getattr(doc, "is_closed", 0)):
		frappe.throw(_("This PM Request is already closed."))
	if has_draft_payment_entry(doc.name):
		from erpnext_extensions.petty_management.services.request_action_policy import MSG_CLOSE_DRAFT_PE

		frappe.throw(str(MSG_CLOSE_DRAFT_PE), title=_("Draft Payment Entry"))

	sync_pm_request_funding_fields(doc)
	doc.reload()
	remaining = flt(doc.remaining_to_pay)
	reason = (close_reason or "").strip()
	detail = (close_reason_detail or "").strip()

	if remaining > _EPS and not reason:
		frappe.throw(_("Close Reason is required when Remaining To Pay is greater than zero."))
	if reason and reason not in CLOSE_REASONS:
		frappe.throw(_("Invalid Close Reason."))
	if reason == "Other" and not detail:
		frappe.throw(_("Close Reason Detail is required when Close Reason is Other."))

	frappe.db.set_value(
		"PM Request",
		doc.name,
		{
			"is_closed": 1,
			"closed_on": now_datetime(),
			"closed_by": frappe.session.user,
			"close_reason": reason or None,
			"close_reason_detail": detail or None,
		},
		update_modified=True,
	)


def close_pm_request_action_flags(doc: Document) -> tuple[bool, str]:
	if doc.docstatus != 1:
		return False, _("Submit the PM Request first.")
	if cint(getattr(doc, "is_closed", 0)):
		return False, _("Already closed.")
	ws = workflow_state_title(doc)
	if ws != "Approved":
		return False, _("Close is only available after approval.")
	if has_draft_payment_entry(doc.name):
		from erpnext_extensions.petty_management.services.request_action_policy import MSG_CLOSE_DRAFT_PE

		return False, str(MSG_CLOSE_DRAFT_PE)
	return True, ""
