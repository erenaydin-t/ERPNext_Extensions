# Copyright (c) 2026, Farbod Siyahpoosh and contributors
# For license information, please see license.txt

"""Workflow-aware settlement eligibility for Payment Request.

Do not rely on ``docstatus == 1`` alone: some deployments drive approval via Workflow while the
document remains unsubmitted. Eligibility is derived from the **active** Workflow for
``Payment Request``: states whose Workflow row ``doc_status`` is ``1`` match Frappe's convention
for “submitted” workflow states (e.g. Approved). If no Workflow exists, fall back to
``docstatus == 1`` (standard ERPNext).
"""

from __future__ import annotations

import frappe

_active_pr_workflow_name: str | None | bool = False


def _get_active_payment_request_workflow_name() -> str | None:
	"""Return active Workflow name for Payment Request, or None."""
	global _active_pr_workflow_name
	if _active_pr_workflow_name is False:
		row = frappe.get_all(
			"Workflow",
			filters={"document_type": "Payment Request", "is_active": 1},
			pluck="name",
			limit=1,
		)
		_active_pr_workflow_name = row[0] if row else None
	return _active_pr_workflow_name  # type: ignore[return-value]


def get_payment_request_settlement_eligible_workflow_states() -> frozenset[str] | None:
	"""Return workflow state names that are settlement-eligible, or None if no Workflow is configured.

	Eligible states are those whose row in the Workflow ``states`` child table has ``doc_status == '1'``.
	This matches the site's workflow definition (e.g. *Approved*) without hardcoding labels.
	"""
	wf_name = _get_active_payment_request_workflow_name()
	if not wf_name:
		return None
	wf = frappe.get_doc("Workflow", wf_name)
	eligible: list[str] = []
	for s in wf.states:
		if str(getattr(s, "doc_status", None) or "0") == "1":
			eligible.append(s.state)
	return frozenset(eligible)


def pr_row_counts_toward_invoice_issuance_ceiling(row: dict) -> bool:
	"""Whether this Payment Request row should count in invoice PR issuance totals."""
	eligible_states = get_payment_request_settlement_eligible_workflow_states()
	if eligible_states is not None:
		ws = (row.get("workflow_state") or "").strip()
		return bool(ws) and ws in eligible_states
	return int(row.get("docstatus") or 0) == 1


def is_payment_request_settlement_eligible(doc) -> bool:
	"""True when PR may show PDC / settlement UI and participate in capacity / ceiling rules.

	* If a Workflow is configured and ``workflow_state`` exists on the DocType: eligible when
	  ``workflow_state`` is one of the Workflow states with ``doc_status == 1``.
	* Otherwise: eligible when ``docstatus == 1`` (no workflow — classic ERPNext).
	"""
	if not doc:
		return False
	doctype = (getattr(doc, "doctype", None) or (doc.get("doctype") if isinstance(doc, dict) else None) or "").strip()
	if doctype and doctype != "Payment Request":
		return False

	meta = frappe.get_meta("Payment Request")
	eligible_states = get_payment_request_settlement_eligible_workflow_states()

	def _docstatus() -> int:
		if isinstance(doc, dict):
			return int(doc.get("docstatus") or 0)
		return int(getattr(doc, "docstatus", None) or 0)

	def _workflow_state() -> str:
		if isinstance(doc, dict):
			return (doc.get("workflow_state") or "").strip()
		return (getattr(doc, "workflow_state", None) or "").strip()

	if meta.has_field("workflow_state") and eligible_states is not None:
		ws = _workflow_state()
		if not ws:
			return False
		return ws in eligible_states

	return _docstatus() == 1


def validate_payment_request_invoice_ceiling_on_save(doc, method=None) -> None:
	"""Validate invoice issuance ceiling when PR is settlement-eligible (not only on submit)."""
	if getattr(doc, "doctype", None) != "Payment Request":
		return
	if not is_payment_request_settlement_eligible(doc):
		return
	# Local import avoids circular import with pdc_settlement_capacity.
	from erpnext_extensions.cheque_management.pdc_settlement_capacity import validate_invoice_pr_issuance_ceiling

	validate_invoice_pr_issuance_ceiling(doc, method)


__all__ = [
	"get_payment_request_settlement_eligible_workflow_states",
	"is_payment_request_settlement_eligible",
	"pr_row_counts_toward_invoice_issuance_ceiling",
	"validate_payment_request_invoice_ceiling_on_save",
]
