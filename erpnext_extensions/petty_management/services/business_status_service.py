# Copyright (c) 2026, ERPNext Extensions contributors
"""Business lifecycle sync — status/payment only; never writes workflow_state."""

from __future__ import annotations

import frappe
from frappe.model.document import Document
from frappe.utils import cint

# PM Request business status (Select options)
REQ_DRAFT = "Draft"
REQ_PENDING_APPROVAL = "Pending Approval"
REQ_WAITING_FOR_PAYMENT = "Waiting for Payment"
REQ_PAID = "Paid"
REQ_CLOSED = "Closed"
REQ_REJECTED = "Rejected"
REQ_CANCELLED = "Cancelled"
# Legacy labels still accepted when reading
REQ_LEGACY_PAYABLE = "Payable"
REQ_LEGACY_PENDING = "Pending"
REQ_LEGACY_APPROVED = "Approved"

# PM Clearance business status
CLR_DRAFT = "Draft"
CLR_PENDING_APPROVAL = "Pending Approval"
CLR_APPROVED = "Approved"
CLR_PENDING_JE = "Pending Journal Entry Submission"
CLR_SETTLED = "Settled"
CLR_REJECTED = "Rejected"
CLR_CANCELLED = "Cancelled"

REQUEST_PENDING_WORKFLOW_TITLES = frozenset(
	{
		"Pending Approval",
		"Pending Manager Approval",
		"Pending CEO Approval",
		"Pending Finance Approval",
	}
)
REQUEST_WAITING_WORKFLOW_TITLES = frozenset(
	{
		"Waiting for Payment",
		"Approved",  # legacy finance-cleared workflow title
	}
)
CLEARANCE_PENDING_WORKFLOW_TITLES = frozenset(
	{
		"Pending Approval",
		"Pending Manager Approval",
		"Pending Finance Review",
	}
)


def _workflow_title(doc: Document) -> str:
	ws = (getattr(doc, "workflow_state", None) or "").strip()
	if not ws:
		return ""
	return (
		frappe.db.get_value("Workflow State", ws, "workflow_state_name") or ws or ""
	).strip()


def _journal_entry_docstatus(journal_entry: str | None) -> int | None:
	if not journal_entry or not frappe.db.exists("Journal Entry", journal_entry):
		return None
	return cint(frappe.db.get_value("Journal Entry", journal_entry, "docstatus"))


def sync_pm_request_business_status(doc: Document) -> str:
	"""Set ``doc.status`` from workflow + payment + close. Never writes ``workflow_state``."""
	if cint(getattr(doc, "docstatus", 0)) == 2:
		doc.status = REQ_CANCELLED
		return doc.status

	ws_title = _workflow_title(doc)
	payment_status = (getattr(doc, "payment_status", None) or "").strip()
	is_closed = cint(getattr(doc, "is_closed", 0))

	if ws_title == "Rejected" or (doc.status or "").strip() == REQ_REJECTED:
		doc.status = REQ_REJECTED
		return doc.status

	if is_closed:
		doc.status = REQ_CLOSED
		return doc.status

	if payment_status == "Paid":
		doc.status = REQ_PAID
		return doc.status

	if ws_title in REQUEST_PENDING_WORKFLOW_TITLES:
		doc.status = REQ_PENDING_APPROVAL
		return doc.status

	if ws_title in REQUEST_WAITING_WORKFLOW_TITLES:
		doc.status = REQ_WAITING_FOR_PAYMENT
		return doc.status

	if not ws_title or ws_title == "Draft" or cint(getattr(doc, "docstatus", 0)) == 0:
		doc.status = REQ_DRAFT
		return doc.status

	# Fallback: keep existing non-empty status if unknown workflow title
	if not (doc.status or "").strip():
		doc.status = REQ_DRAFT
	return doc.status


def sync_pm_clearance_business_status(doc: Document, *, persist: bool = False) -> str:
	"""Set ``doc.status`` from JE + approval workflow. Never writes ``workflow_state``."""
	if cint(getattr(doc, "docstatus", 0)) == 2:
		lifecycle = CLR_CANCELLED
	else:
		je = (getattr(doc, "journal_entry", None) or "").strip()
		je_ds = _journal_entry_docstatus(je) if je else None
		ws_title = _workflow_title(doc)

		if je_ds == 1:
			lifecycle = CLR_SETTLED
		elif je_ds == 0:
			lifecycle = CLR_PENDING_JE
		elif ws_title == "Rejected":
			lifecycle = CLR_REJECTED
		elif ws_title == "Approved":
			lifecycle = CLR_APPROVED
		elif ws_title in CLEARANCE_PENDING_WORKFLOW_TITLES:
			lifecycle = CLR_PENDING_APPROVAL
		elif ws_title in ("Pending Journal Entry Submission", "Settled"):
			# Stale accounting titles still on workflow_state before migration rewind:
			# treat as Approved approval-wise for status derivation without JE.
			lifecycle = CLR_APPROVED if je_ds is None else (
				CLR_SETTLED if je_ds == 1 else CLR_PENDING_JE
			)
		elif not ws_title or ws_title == "Draft" or cint(getattr(doc, "docstatus", 0)) == 0:
			lifecycle = CLR_DRAFT
		else:
			lifecycle = (getattr(doc, "status", None) or CLR_DRAFT).strip() or CLR_DRAFT

	doc.status = lifecycle

	if persist and getattr(doc, "name", None):
		frappe.db.set_value(
			"PM Clearance",
			doc.name,
			{"status": lifecycle},
			update_modified=False,
		)

	return lifecycle


def request_is_finance_cleared(doc: Document) -> bool:
	"""Business-ready for funding actions (Create PE / Close eligibility base)."""
	st = (getattr(doc, "status", None) or "").strip()
	if st in (REQ_WAITING_FOR_PAYMENT, REQ_LEGACY_PAYABLE, REQ_LEGACY_APPROVED, REQ_PAID, REQ_CLOSED):
		return True
	ws = _workflow_title(doc)
	return ws in REQUEST_WAITING_WORKFLOW_TITLES


def clearance_is_finance_approved(doc: Document) -> bool:
	"""Settle allowed when business status is Approved (not Settled/Pending JE)."""
	st = (getattr(doc, "status", None) or "").strip()
	if st in (CLR_REJECTED, CLR_CANCELLED, CLR_DRAFT):
		return False
	if st == CLR_APPROVED:
		return True
	# After migration, Approved workflow + Settled status means already settled
	return False
