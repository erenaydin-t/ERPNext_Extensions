# Copyright (c) 2026, Farbod Siyahpoosh and contributors
# For license information, please see license.txt

"""Post Dated Cheque **allocation** layer (child table ``allocations``).

Allocations tie cheque amounts to invoices, advances, payment requests, or other references for
**reporting and planning**. They do **not** post GL vouchers — workflow-driven movement uses
:class:`~erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque.PostDatedCheque`
and :func:`~erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque.build_pdc_journal_entry_data` only.

Settlement capacity for Sales / Purchase Invoice and Payment Request is enforced against
``outstanding_amount`` (net of submitted Payment Entry) and effective PDC reservations; see
:mod:`~erpnext_extensions.cheque_management.pdc_settlement_capacity`. **Payable** cheques skip this
capacity check once allocations are effective (**Registered** onward) because register JE settles PI/PR in
ERPNext natively.

**Effective vs planning**

* **Receivable:** allocation rows become operationally **effective** from **Registered** onward.
* **Payable:** **Draft** is planning-only; **Registered** onward are effective (register settlement).

See :meth:`erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque.PostDatedCheque.validate` for call order (summary sync → row validation → status awareness).
"""

from __future__ import annotations

import re

import frappe
from frappe.utils import flt

from erpnext_extensions.cheque_management.pdc_settlement_capacity import (
	SETTLEMENT_REFERENCE_DOCTYPES,
	get_invoice_remaining_capacity,
	get_pr_remaining_capacity,
)
from erpnext_extensions.cheque_management.pdc_workflow_state_machine import (
	CHEQUE_DIRECTION_PAYABLE,
	CHEQUE_DIRECTION_RECEIVABLE,
	WORKFLOW_CANCELLED,
	WORKFLOW_CLEARED,
	WORKFLOW_DRAFT,
	WORKFLOW_ISSUED,
	WORKFLOW_REGISTERED,
	WORKFLOW_REPLACED,
	WORKFLOW_RETURNED,
	normalize_workflow_state_value,
)

_EPS = 1e-6

_PR_INWARD = "Inward"
_PR_OUTWARD = "Outward"


def _payable_skip_pdc_settlement_capacity_validation(doc) -> bool:
	"""True when PI/PR rows must not be gated on PDC capacity (native register JE settles in ERPNext).

	* **Registered onward:** allocations are effective; ledger + register JE are authoritative.
	* **Draft → Registered transition:** :meth:`~frappe.model.document.Document.validate` runs
	  ``_validate_allocations`` before workflow pre-save in some paths; use ``get_doc_before_save`` so we
	  still skip capacity on the same save that registers the cheque.
	"""
	direction = (getattr(doc, "cheque_direction", None) or "").strip()
	if direction != CHEQUE_DIRECTION_PAYABLE:
		return False
	ws = getattr(doc, "workflow_state", None)
	if is_pdc_allocation_effective(direction, ws):
		return True
	before = doc.get_doc_before_save() if hasattr(doc, "get_doc_before_save") else None
	if before is None:
		return False
	prev = normalize_workflow_state_value(before.get("workflow_state"))
	curr = normalize_workflow_state_value(ws)
	return prev == WORKFLOW_DRAFT and curr == WORKFLOW_REGISTERED


def pdc_allocation_effective_milestone_workflow_state(cheque_direction: str | None) -> str | None:
	"""First ``workflow_state`` at which allocation rows are treated as effective (not planning-only).

	Returns ``None`` if ``cheque_direction`` is not Receivable/Payable.
	"""
	if cheque_direction == CHEQUE_DIRECTION_RECEIVABLE:
		return WORKFLOW_REGISTERED
	if cheque_direction == CHEQUE_DIRECTION_PAYABLE:
		return WORKFLOW_REGISTERED
	return None


def is_pdc_allocation_effective(cheque_direction: str | None, workflow_state: str | None) -> bool:
	"""Whether allocations should be treated as effective for the current workflow step."""
	ws = normalize_workflow_state_value(workflow_state)
	if cheque_direction == CHEQUE_DIRECTION_RECEIVABLE:
		return ws != WORKFLOW_DRAFT
	if cheque_direction == CHEQUE_DIRECTION_PAYABLE:
		return ws in (
			WORKFLOW_REGISTERED,
			WORKFLOW_ISSUED,
			WORKFLOW_CLEARED,
			WORKFLOW_RETURNED,
			WORKFLOW_REPLACED,
			WORKFLOW_CANCELLED,
		)
	return False


def is_pdc_allocation_draft_only(cheque_direction: str | None, workflow_state: str | None) -> bool:
	"""True when allocation rows may exist but are planning data only."""
	if not pdc_allocation_effective_milestone_workflow_state(cheque_direction):
		return True
	return not is_pdc_allocation_effective(cheque_direction, workflow_state)


def sync_pdc_allocation_summary_amounts(doc) -> None:
	"""Set ``allocated_amount`` and ``unallocated_amount`` from child rows; enforce sum ≤ cheque amount.

	Mutates ``doc`` in place. Raises via ``frappe.throw`` when totals exceed ``cheque_amount``.
	"""
	total = 0.0
	for row in doc.allocations or []:
		total += float(getattr(row, "allocated_amount", None) or 0)

	cheque_amt = float(getattr(doc, "cheque_amount", None) or 0)
	doc.allocated_amount = total
	doc.unallocated_amount = cheque_amt - total

	if cheque_amt and total > cheque_amt + _EPS:
		frappe.throw(
			frappe._("Allocated Amount ({0}) cannot exceed Cheque Amount ({1}).").format(
				doc.allocated_amount, doc.cheque_amount
			),
			title=frappe._("PDC Allocation"),
		)


def _parse_other_settlement_allowlist(raw: str | None) -> frozenset[str]:
	if not raw:
		return frozenset()
	parts = re.split(r"[\s,]+", raw.strip())
	return frozenset(p.strip() for p in parts if p.strip())


def get_pdc_other_settlement_allowlist(company: str | None) -> frozenset[str]:
	"""DocType names allowed for **Other Settlement** rows for ``company`` (from PDC Settings)."""
	if not (company or "").strip():
		return frozenset()
	try:
		raw = frappe.db.get_value("PDC Settings", company, "other_settlement_allowed_doctypes")
	except RuntimeError:
		# No request context / DB (e.g. bare unit tests without ``frappe.init``).
		return frozenset()
	return _parse_other_settlement_allowlist(raw)


def _pdc_effective_currency(doc) -> str | None:
	cur = (getattr(doc, "currency", None) or "").strip()
	if cur:
		return cur
	co = (getattr(doc, "company", None) or "").strip()
	if not co:
		return None
	return frappe.db.get_value("Company", co, "default_currency")


def _read_sales_invoice_for_pdc_allocation(name: str) -> dict | None:
	if not name or not frappe.db.exists("Sales Invoice", name):
		return None
	return frappe.db.get_value(
		"Sales Invoice",
		name,
		["company", "currency", "customer", "docstatus", "outstanding_amount"],
		as_dict=True,
	)


def _read_purchase_invoice_for_pdc_allocation(name: str) -> dict | None:
	if not name or not frappe.db.exists("Purchase Invoice", name):
		return None
	return frappe.db.get_value(
		"Purchase Invoice",
		name,
		["company", "currency", "supplier", "docstatus", "outstanding_amount"],
		as_dict=True,
	)


def _read_payment_request_for_pdc_allocation(name: str) -> dict | None:
	if not name or not frappe.db.exists("Payment Request", name):
		return None
	return frappe.db.get_value(
		"Payment Request",
		name,
		[
			"company",
			"currency",
			"party_type",
			"party",
			"payment_request_type",
			"docstatus",
			"workflow_state",
			"outstanding_amount",
			"status",
		],
		as_dict=True,
	)


def _read_other_settlement_document(doctype: str, name: str) -> dict | None:
	if not doctype or not name or not frappe.db.exists(doctype, name):
		return None
	doc = frappe.get_doc(doctype, name)
	out: dict = {
		"company": getattr(doc, "company", None),
		"currency": getattr(doc, "currency", None),
		"docstatus": getattr(doc, "docstatus", None),
	}
	if getattr(doc, "party_type", None) is not None and getattr(doc, "party", None) is not None:
		out["party_type"] = doc.party_type
		out["party"] = doc.party
	elif getattr(doc, "customer", None):
		out["party_anchor"] = "customer"
		out["customer"] = doc.customer
	elif getattr(doc, "supplier", None):
		out["party_anchor"] = "supplier"
		out["supplier"] = doc.supplier
	return out


def _party_matches_pdc_snapshot(
	cheque_direction: str,
	party_type: str | None,
	party: str | None,
	ref_doctype: str,
	snap: dict,
) -> bool:
	pt = (party_type or "").strip()
	pp = (party or "").strip()
	if ref_doctype == "Sales Invoice":
		return snap.get("customer") == pp
	if ref_doctype == "Purchase Invoice":
		return snap.get("supplier") == pp
	if ref_doctype == "Payment Request":
		return snap.get("party_type") == pt and snap.get("party") == pp
	if snap.get("party_type") is not None and snap.get("party") is not None:
		return snap.get("party_type") == pt and snap.get("party") == pp
	if snap.get("party_anchor") == "customer" and cheque_direction == CHEQUE_DIRECTION_RECEIVABLE:
		return snap.get("customer") == pp
	if snap.get("party_anchor") == "supplier" and cheque_direction == CHEQUE_DIRECTION_PAYABLE:
		return snap.get("supplier") == pp
	return False


def _currency_matches(pdc_currency: str | None, ref_currency: str | None) -> bool:
	a = (pdc_currency or "").strip()
	b = (ref_currency or "").strip()
	return bool(a and b and a == b)


def sanitize_pdc_allocation_child_rows(doc) -> None:
	"""Remove allocation rows that are completely empty (no amount, type, or reference)."""
	alloc = getattr(doc, "allocations", None) or []
	if not alloc:
		return
	for row in list(alloc):
		amt = flt(getattr(row, "allocated_amount", None))
		at = (getattr(row, "allocation_type", None) or "").strip()
		rdt = (getattr(row, "reference_doctype", None) or "").strip()
		rnm = (getattr(row, "reference_name", None) or "").strip()
		if amt <= 0 and not at and not rdt and not rnm:
			doc.remove(row)


def autofill_pdc_allocations_from_parent_reference(doc) -> None:
	"""Prefill incomplete allocation rows when PDC is created from SI/PI (parent ``reference_doctype`` / ``reference_name``)."""
	pdt = (getattr(doc, "reference_doctype", None) or "").strip()
	pnm = (getattr(doc, "reference_name", None) or "").strip()
	if pdt not in ("Sales Invoice", "Purchase Invoice") or not pnm:
		return
	ch = flt(getattr(doc, "cheque_amount", None))
	for row in getattr(doc, "allocations", None) or []:
		rdt = (getattr(row, "reference_doctype", None) or "").strip()
		rnm = (getattr(row, "reference_name", None) or "").strip()
		if rdt and rnm:
			continue
		if not (getattr(row, "allocation_type", None) or "").strip():
			row.allocation_type = "Against Invoice"
		row.reference_doctype = pdt
		row.reference_name = pnm
		if ch > 0 and flt(getattr(row, "allocated_amount", None)) <= 0:
			row.allocated_amount = ch


def validate_pdc_allocation_rows(doc) -> None:
	"""Validate ``allocations`` child rows; raises ``frappe`` validation if rules fail."""
	if not (doc.allocations or []):
		return

	company = (getattr(doc, "company", None) or "").strip()
	party_type = getattr(doc, "party_type", None)
	party = getattr(doc, "party", None)
	direction = (getattr(doc, "cheque_direction", None) or "").strip()
	pdc_currency = _pdc_effective_currency(doc)
	parent_name = getattr(doc, "name", None)
	allowlist = get_pdc_other_settlement_allowlist(company) if company else frozenset()

	total = 0.0
	seen_ref_pairs: set[tuple[str, str]] = set()
	empty_advance_row_seen = False

	for i, row in enumerate(doc.allocations or [], start=1):
		amt = float(getattr(row, "allocated_amount", None) or 0)
		allocation_type = (getattr(row, "allocation_type", None) or "").strip()
		ref_dt = (getattr(row, "reference_doctype", None) or "").strip()
		ref_nm = (getattr(row, "reference_name", None) or "").strip()

		if amt > 0 and not allocation_type:
			frappe.throw(
				frappe._(
					"Allocation row {0} is incomplete: please set Allocation Type and reference fields as required."
				).format(i),
				title=frappe._("PDC Allocation"),
			)

		if amt <= 0:
			frappe.throw(
				frappe._("Allocation row {0}: Allocated Amount must be greater than zero.").format(i),
				title=frappe._("PDC Allocation"),
			)
		total += amt

		if bool(ref_dt) ^ bool(ref_nm):
			frappe.throw(
				frappe._(
					"Allocation row {0}: Reference DocType and Reference Name must both be set (or both empty for Advance)."
				).format(i),
				title=frappe._("PDC Allocation"),
			)

		if ref_dt == "Sales Invoice" and direction == CHEQUE_DIRECTION_PAYABLE:
			frappe.throw(
				frappe._("Allocation row {0}: Payable PDC cannot allocate to Sales Invoice.").format(i),
				title=frappe._("PDC Allocation"),
			)
		if ref_dt == "Purchase Invoice" and direction == CHEQUE_DIRECTION_RECEIVABLE:
			frappe.throw(
				frappe._("Allocation row {0}: Receivable PDC cannot allocate to Purchase Invoice.").format(i),
				title=frappe._("PDC Allocation"),
			)

		if allocation_type == "Advance":
			if ref_dt or ref_nm:
				frappe.throw(
					frappe._(
						"Allocation row {0}: Advance allocation must leave Reference DocType and Reference Name empty."
					).format(i),
					title=frappe._("PDC Allocation"),
				)
			if empty_advance_row_seen:
				frappe.throw(
					frappe._(
						"Allocation row {0}: Only one Advance row without reference is allowed per Post Dated Cheque."
					).format(i),
					title=frappe._("PDC Allocation"),
				)
			empty_advance_row_seen = True
			continue

		if allocation_type == "Payment Request":
			if not ref_dt or not ref_nm:
				frappe.throw(
					frappe._("Allocation row {0}: Reference is required for Allocation Type Payment Request.").format(i),
					title=frappe._("PDC Allocation"),
				)
			if ref_dt != "Payment Request":
				frappe.throw(
					frappe._(
						"Allocation row {0}: Reference DocType must be Payment Request when Allocation Type is Payment Request."
					).format(i),
					title=frappe._("PDC Allocation"),
				)
		elif allocation_type == "Against Invoice":
			if not ref_dt or not ref_nm:
				frappe.throw(
					frappe._("Allocation row {0}: Reference is required for Allocation Type Against Invoice.").format(i),
					title=frappe._("PDC Allocation"),
				)
			if direction == CHEQUE_DIRECTION_RECEIVABLE and ref_dt != "Sales Invoice":
				frappe.throw(
					frappe._(
						"Allocation row {0}: Receivable PDC invoice allocation must reference Sales Invoice."
					).format(i),
					title=frappe._("PDC Allocation"),
				)
			if direction == CHEQUE_DIRECTION_PAYABLE and ref_dt != "Purchase Invoice":
				frappe.throw(
					frappe._(
						"Allocation row {0}: Payable PDC invoice allocation must reference Purchase Invoice."
					).format(i),
					title=frappe._("PDC Allocation"),
				)
		elif allocation_type == "Other Settlement":
			if not ref_dt or not ref_nm:
				frappe.throw(
					frappe._(
						"Allocation row {0}: Reference DocType and Reference Name are required for Other Settlement."
					).format(i),
					title=frappe._("PDC Allocation"),
				)
			if not allowlist:
				frappe.throw(
					frappe._(
						"Allocation row {0}: Other Settlement is not allowed until allowed DocTypes are configured in PDC Settings for this company."
					).format(i),
					title=frappe._("PDC Allocation"),
				)
			if ref_dt not in allowlist:
				frappe.throw(
					frappe._(
						"Allocation row {0}: DocType {1} is not in the Other Settlement allowlist (PDC Settings)."
					).format(i, ref_dt),
					title=frappe._("PDC Allocation"),
				)
		else:
			frappe.throw(
				frappe._("Allocation row {0}: Unknown Allocation Type {1}.").format(i, allocation_type),
				title=frappe._("PDC Allocation"),
			)

		key = (ref_dt, ref_nm)
		if key in seen_ref_pairs:
			frappe.throw(
				frappe._(
					"Allocation row {0}: Duplicate reference to {1} {2}. Remove duplicate rows or merge amounts in one row."
				).format(i, ref_dt, ref_nm),
				title=frappe._("PDC Allocation"),
			)
		seen_ref_pairs.add(key)

	cheque_amt = float(getattr(doc, "cheque_amount", None) or 0)
	if cheque_amt and total > cheque_amt + _EPS:
		frappe.throw(
			frappe._("Total Allocated Amount ({0}) cannot exceed Cheque Amount ({1}).").format(total, doc.cheque_amount),
			title=frappe._("PDC Allocation"),
		)

	if not company:
		frappe.throw(
			frappe._("Company is required before validating allocations."),
			title=frappe._("PDC Allocation"),
		)
	if not pdc_currency:
		frappe.throw(
			frappe._("Currency could not be resolved for this Post Dated Cheque; set Currency or Company."),
			title=frappe._("PDC Allocation"),
		)

	for i, row in enumerate(doc.allocations or [], start=1):
		allocation_type = (getattr(row, "allocation_type", None) or "").strip()
		if allocation_type == "Advance":
			continue

		ref_dt = (getattr(row, "reference_doctype", None) or "").strip()
		ref_nm = (getattr(row, "reference_name", None) or "").strip()
		amt = float(getattr(row, "allocated_amount", None) or 0)

		snap: dict | None = None
		if ref_dt == "Sales Invoice":
			snap = _read_sales_invoice_for_pdc_allocation(ref_nm)
		elif ref_dt == "Purchase Invoice":
			snap = _read_purchase_invoice_for_pdc_allocation(ref_nm)
		elif ref_dt == "Payment Request":
			snap = _read_payment_request_for_pdc_allocation(ref_nm)
		else:
			snap = _read_other_settlement_document(ref_dt, ref_nm)

		if not snap:
			frappe.throw(
				frappe._("Allocation row {0}: {1} {2} was not found.").format(i, ref_dt, ref_nm),
				title=frappe._("PDC Allocation"),
			)

		if snap.get("docstatus") == 2:
			frappe.throw(
				frappe._("Allocation row {0}: {1} {2} is cancelled.").format(i, ref_dt, ref_nm),
				title=frappe._("PDC Allocation"),
			)

		if ref_dt == "Payment Request":
			from erpnext_extensions.cheque_management.pdc_payment_request_eligibility import (
				is_payment_request_settlement_eligible,
			)

			if not is_payment_request_settlement_eligible(snap):
				frappe.throw(
					frappe._(
						"Allocation row {0}: Payment Request {1} must be in an approved / settlement-eligible workflow state (or submitted when no workflow applies)."
					).format(i, ref_nm),
					title=frappe._("PDC Allocation"),
				)
		elif ref_dt in ("Sales Invoice", "Purchase Invoice") and int(snap.get("docstatus") or 0) != 1:
			frappe.throw(
				frappe._("Allocation row {0}: {1} {2} must be submitted.").format(i, ref_dt, ref_nm),
				title=frappe._("PDC Allocation"),
			)

		if (snap.get("company") or "").strip() != company:
			frappe.throw(
				frappe._("Allocation row {0}: Company on {1} does not match this Post Dated Cheque.").format(i, ref_dt),
				title=frappe._("PDC Allocation"),
			)

		if not _currency_matches(pdc_currency, snap.get("currency")):
			frappe.throw(
				frappe._("Allocation row {0}: Currency on {1} must match the Post Dated Cheque currency ({2}).").format(
					i, ref_dt, pdc_currency
				),
				title=frappe._("PDC Allocation"),
			)

		if not _party_matches_pdc_snapshot(direction, party_type, party, ref_dt, snap):
			frappe.throw(
				frappe._("Allocation row {0}: Party on {1} does not match this Post Dated Cheque.").format(i, ref_dt),
				title=frappe._("PDC Allocation"),
			)

		if ref_dt == "Payment Request":
			pr_type = (snap.get("payment_request_type") or "").strip()
			if direction == CHEQUE_DIRECTION_RECEIVABLE and pr_type != _PR_INWARD:
				frappe.throw(
					frappe._(
						"Allocation row {0}: Receivable PDC may only allocate to Inward Payment Requests."
					).format(i),
					title=frappe._("PDC Allocation"),
				)
			if direction == CHEQUE_DIRECTION_PAYABLE and pr_type != _PR_OUTWARD:
				frappe.throw(
					frappe._(
						"Allocation row {0}: Payable PDC may only allocate to Outward Payment Requests."
					).format(i),
					title=frappe._("PDC Allocation"),
				)

		outstanding = flt(snap.get("outstanding_amount"))
		if ref_dt in SETTLEMENT_REFERENCE_DOCTYPES:
			# Payable: PI/PR settlement at/after Register is via register Journal Entry + ERPNext ledger—not
			# ``get_*_remaining_capacity`` (avoids double-count with native settlement).
			if direction == CHEQUE_DIRECTION_PAYABLE and _payable_skip_pdc_settlement_capacity_validation(doc):
				continue
			# Contract: remaining capacity is computed from canonical service layer (ledger outstanding for invoices,
			# PR grand_total for Payment Request), and always excludes this cheque during validation.
			if ref_dt == "Payment Request":
				available = get_pr_remaining_capacity(ref_nm, exclude_pdc=parent_name)
			elif ref_dt in ("Sales Invoice", "Purchase Invoice"):
				available = get_invoice_remaining_capacity(ref_dt, ref_nm, exclude_pdc=parent_name)
			else:
				# Defensive fallback: should not happen because SETTLEMENT_REFERENCE_DOCTYPES is fixed.
				available = outstanding
			if amt > available + _EPS:
				frappe.throw(
					frappe._(
						"Allocation row {0}: Allocated Amount ({1}) exceeds remaining settlement capacity on {2} {3}. "
						"Reference outstanding is {4}; remaining capacity for this cheque is {5} (after other effective Post Dated Cheque allocations and submitted Payment Entries reflected in outstanding)."
					).format(i, amt, ref_dt, ref_nm, outstanding, available),
					title=frappe._("PDC Allocation"),
				)


def validate_pdc_allocation_workflow_milestone(doc) -> None:
	"""Defensive check: effective allocation must not appear before direction-specific milestone.

	Payable allocations become settlement-effective at **Registered** (register JE). Issued is operational only.
	Receivable: effective from **Registered** onward. ``is_pdc_allocation_effective`` is False for Draft, so
	the checks below only fire on inconsistent documents.
	"""
	if not (doc.allocations or []):
		return
	ws = normalize_workflow_state_value(getattr(doc, "workflow_state", None))
	if doc.cheque_direction == CHEQUE_DIRECTION_RECEIVABLE and ws == WORKFLOW_DRAFT and is_pdc_allocation_effective(
		doc.cheque_direction, doc.workflow_state
	):
		frappe.throw(
			frappe._("Receivable cheque allocation cannot be effective before Registered."),
			title=frappe._("PDC Allocation"),
		)
	if doc.cheque_direction == CHEQUE_DIRECTION_PAYABLE and ws == WORKFLOW_DRAFT and is_pdc_allocation_effective(
		doc.cheque_direction, doc.workflow_state
	):
		frappe.throw(
			frappe._("Payable cheque allocation cannot be effective before Registered."),
			title=frappe._("PDC Allocation"),
		)


__all__ = [
	"autofill_pdc_allocations_from_parent_reference",
	"get_pdc_other_settlement_allowlist",
	"is_pdc_allocation_draft_only",
	"is_pdc_allocation_effective",
	"pdc_allocation_effective_milestone_workflow_state",
	"sanitize_pdc_allocation_child_rows",
	"sync_pdc_allocation_summary_amounts",
	"validate_pdc_allocation_rows",
	"validate_pdc_allocation_workflow_milestone",
]
