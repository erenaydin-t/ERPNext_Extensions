# Copyright (c) 2026, Farbod Siyahpoosh and contributors
# For license information, please see license.txt

"""Synchronize **Payment Request** ``status`` / ``outstanding_amount`` with settlement coverage.

ERPNext updates **Payment Request** from **Payment Entry** via
``update_payment_requests_as_per_pe_references``. This module **recomputes** the PR after PE and/or PDC
events so both sources match one model:

	``covered_amount =`` submitted **Payment Entry** allocations ``+`` effective **PDC** allocations

	``outstanding_amount = grand_total - covered_amount``

``status`` follows the same Initiated / Requested / Partially Paid / Paid rule as
``update_payment_requests_as_per_pe_references``, applied to that effective outstanding (see
``_status_from_outstanding_like_erpnext``). Effective PDC sums use
:func:`~erpnext_extensions.cheque_management.pdc_settlement_capacity.sum_effective_pdc_allocations_to_reference`.
"""

from __future__ import annotations

import frappe
from frappe.utils import flt

from erpnext_extensions.cheque_management.pdc_payment_request_eligibility import is_payment_request_settlement_eligible
from erpnext_extensions.cheque_management.pdc_settlement_capacity import (
	sum_effective_pdc_allocations_to_reference,
	sum_payment_entry_allocations_to_payment_request,
)

_PR_EPS = 1e-6


def payment_request_outstanding_after_payment_entries(pr_name: str) -> float:
	"""``grand_total`` minus submitted PE allocations only (no PDC); useful for PE-only checks."""
	pr = frappe.db.get_value(
		"Payment Request",
		pr_name,
		["grand_total", "docstatus", "workflow_state"],
		as_dict=True,
	)
	if not pr or not is_payment_request_settlement_eligible(pr):
		return 0.0
	gt = flt(pr.grand_total)
	pe_sum = sum_payment_entry_allocations_to_payment_request(pr_name)
	prec = frappe.get_precision("Payment Request", "outstanding_amount")
	return flt(gt - pe_sum, prec)


def _status_from_outstanding_like_erpnext(
	*,
	grand_total: float,
	effective_outstanding: float,
	payment_request_type: str | None,
) -> str:
	"""Mirror ``update_payment_requests_as_per_pe_references`` status selection (ERPNext)."""
	gt = flt(grand_total)
	o = flt(effective_outstanding)
	if abs(o - gt) <= _PR_EPS:
		return "Initiated" if (payment_request_type or "").strip() == "Outward" else "Requested"
	if abs(o) <= _PR_EPS:
		return "Paid"
	return "Partially Paid"


def sync_payment_request_status_from_settlement(pr_name: str | None) -> None:
	"""Set **Payment Request** ``status`` / ``outstanding_amount`` from PE + effective PDC coverage."""
	nm = (pr_name or "").strip()
	if not nm or not frappe.db.exists("Payment Request", nm):
		return

	meta = frappe.db.get_value(
		"Payment Request",
		nm,
		["docstatus", "status", "grand_total", "payment_request_type", "workflow_state"],
		as_dict=True,
	)
	if not meta or not is_payment_request_settlement_eligible(meta):
		return

	st = (meta.status or "").strip()
	if st in ("Cancelled", "Failed"):
		return

	gt = flt(meta.grand_total)
	pr_type = (meta.payment_request_type or "").strip()
	prec = frappe.get_precision("Payment Request", "outstanding_amount")

	pe_sum = sum_payment_entry_allocations_to_payment_request(nm)
	pdc_sum = sum_effective_pdc_allocations_to_reference("Payment Request", nm)
	covered = flt(pe_sum + pdc_sum, prec)
	new_os = flt(gt - covered, prec)
	if new_os < 0:
		new_os = flt(0, prec)
	elif new_os > gt + _PR_EPS:
		new_os = flt(gt, prec)

	# Do not override integration-specific states when amount remains due (ERPNext **Payment Ordered** path).
	if st == "Payment Ordered" and new_os > _PR_EPS:
		return

	new_status = _status_from_outstanding_like_erpnext(
		grand_total=gt,
		effective_outstanding=new_os,
		payment_request_type=pr_type,
	)
	updates = {"status": new_status, "outstanding_amount": new_os}

	current_os = flt(frappe.db.get_value("Payment Request", nm, "outstanding_amount"))
	current_st = (frappe.db.get_value("Payment Request", nm, "status") or "").strip()
	if abs(flt(updates["outstanding_amount"]) - current_os) <= _PR_EPS and updates["status"] == current_st:
		return

	frappe.db.set_value("Payment Request", nm, updates)


def _iter_pr_names_from_pdc_allocations(doc) -> list[str]:
	out: list[str] = []
	for row in doc.get("allocations") or []:
		if getattr(row, "reference_doctype", None) == "Payment Request" and getattr(row, "reference_name", None):
			out.append(row.reference_name.strip())
	return list(dict.fromkeys(out))


def on_post_dated_cheque_changed(doc, method=None):
	"""Doc hook: submitted PDC changes can change effective coverage on linked Payment Requests."""
	if not doc or doc.doctype != "Post Dated Cheque":
		return
	for pr in _iter_pr_names_from_pdc_allocations(doc):
		sync_payment_request_status_from_settlement(pr)


def on_payment_entry_changed(doc, method=None):
	"""Doc hook: PE submit/cancel; re-sync Payment Request settlement fields (PE + PDC)."""
	if not doc or doc.doctype != "Payment Entry":
		return
	names: list[str] = []
	for row in doc.get("references") or []:
		pr = getattr(row, "payment_request", None)
		if pr:
			names.append(pr.strip())
		elif getattr(row, "reference_doctype", None) == "Payment Request" and getattr(row, "reference_name", None):
			names.append(row.reference_name.strip())
	for pr in dict.fromkeys(names):
		sync_payment_request_status_from_settlement(pr)


__all__ = [
	"on_payment_entry_changed",
	"on_post_dated_cheque_changed",
	"payment_request_outstanding_after_payment_entries",
	"sync_payment_request_status_from_settlement",
]
