# Copyright (c) 2026, Farbod Siyahpoosh and contributors
# For license information, please see license.txt

"""Read-only settlement visibility for Sales Invoice, Purchase Invoice, and Payment Request.

SI/PI use Payment Ledger outstanding and :mod:`pdc_settlement_capacity` for ``remaining_balance``.
Payment Request uses ``grand_total - PE - effective PDC`` for ledger/document outstanding and remaining
(so the desk never mixes in stale DB ``outstanding_amount`` or capacity-only zeros).
"""

from __future__ import annotations

import frappe
from frappe.utils import flt

from erpnext_extensions.cheque_management.pdc_payment_request_eligibility import is_payment_request_settlement_eligible
from erpnext_extensions.cheque_management.pdc_settlement_capacity import (
	SETTLEMENT_REFERENCE_DOCTYPES,
	get_remaining_settlement_capacity,
	get_invoice_ledger_outstanding,
	sum_effective_pdc_allocations_via_payment_request_to_invoice,
	sum_payment_entry_allocations_to_payment_request,
	sum_effective_pdc_allocations_to_reference,
	sum_payment_entry_allocations_to_reference,
)


def get_settlement_summary_for_reference(
	reference_doctype: str | None,
	reference_name: str | None,
) -> dict | None:
	"""Return a normalized settlement summary dict, or ``None`` if not applicable.

	* ``financial_basis_amount`` — ``grand_total`` on the reference (document total).
	* ``payment_entry_amount`` — sum of submitted Payment Entry allocations against this reference.
	* ``effective_pdc_amount`` — sum of effective Post Dated Cheque allocation rows (Step 2 rules).
	* ``document_outstanding`` — for SI/PI: Payment Ledger outstanding; for **Payment Request**:
	  ``grand_total - submitted PE - effective PDC`` (not the raw DB ``outstanding_amount``, which is often 0
	  on draft PRs before ERPNext/sync updates).
	* ``remaining_balance`` — SI/PI: Step 2 capacity (ledger outstanding minus effective PDC). PR:
	  ``grand_total - PE - effective PDC`` (same numbers as ``document_outstanding``).
	"""
	rdt = (reference_doctype or "").strip()
	rnm = (reference_name or "").strip()
	if rdt not in SETTLEMENT_REFERENCE_DOCTYPES or not rnm:
		return None
	if not frappe.db.exists(rdt, rnm):
		return None

	frappe.has_permission(rdt, "read", rnm, throw=True)

	meta = frappe.get_meta(rdt)
	if not meta.has_field("grand_total") or not meta.has_field("outstanding_amount"):
		return None

	fields = ["grand_total", "outstanding_amount", "company", "currency", "docstatus"]
	# Some doctypes (e.g. Sales Invoice) may not have workflow_state column in all installs.
	if meta.has_field("workflow_state"):
		fields.append("workflow_state")

	row = frappe.db.get_value(
		rdt,
		rnm,
		fields,
		as_dict=True,
	)
	if not row:
		return None

	company = (row.get("company") or "").strip()
	currency = (row.get("currency") or "").strip()

	gt = flt(row.get("grand_total"))

	if rdt == "Payment Request":
		# Do **not** use raw ``outstanding_amount`` from DB for display: ERPNext often leaves it 0 for Draft /
		# pre-submit PRs. The desk must show one consistent decomposition everywhere:
		#   unpaid / remaining = grand_total - submitted PE - effective PDC
		# Do not derive ``remaining_balance`` from :func:`get_remaining_settlement_capacity` here: that path
		# calls ``get_pr_remaining_capacity``, which returns 0 when the PR is not settlement-eligible and can
		# disagree with the unpaid amount shown beside ``document_outstanding`` / the table.
		if not is_payment_request_settlement_eligible(row):
			pe_sum = 0.0
			pdc_direct = 0.0
			pdc_via = 0.0
			pdc_total = 0.0
			computed_unpaid = flt(gt - pe_sum - pdc_total)
			return {
				"reference_doctype": rdt,
				"reference_name": rnm,
				"company": company,
				"currency": currency,
				"financial_basis_amount": gt,
				"payment_entry_amount": pe_sum,
				"effective_pdc_amount_direct": pdc_direct,
				"effective_pdc_amount_via_pr": pdc_via,
				"effective_pdc_amount": 0.0,
				"ledger_outstanding": computed_unpaid,
				"document_outstanding": computed_unpaid,
				"remaining_balance": computed_unpaid,
				"payment_request_settlement_eligible": False,
			}

		pe_sum = sum_payment_entry_allocations_to_payment_request(rnm)
		pdc_direct = sum_effective_pdc_allocations_to_reference("Payment Request", rnm)
		pdc_via = 0.0
		pdc_total = flt(pdc_direct) + flt(pdc_via)
		computed_unpaid = flt(gt - pe_sum - pdc_total)
		return {
			"reference_doctype": rdt,
			"reference_name": rnm,
			"company": company,
			"currency": currency,
			"financial_basis_amount": gt,
			"payment_entry_amount": pe_sum,
			"effective_pdc_amount_direct": pdc_direct,
			"effective_pdc_amount_via_pr": pdc_via,
			"effective_pdc_amount": pdc_total,
			"ledger_outstanding": computed_unpaid,
			"document_outstanding": computed_unpaid,
			"remaining_balance": computed_unpaid,
			"payment_request_settlement_eligible": is_payment_request_settlement_eligible(row),
		}
	else:
		pe_sum = sum_payment_entry_allocations_to_reference(rdt, rnm, company=company)
		pdc_direct = sum_effective_pdc_allocations_to_reference(rdt, rnm)
		pdc_via = sum_effective_pdc_allocations_via_payment_request_to_invoice(rdt, rnm)
		ledger_out = flt(get_invoice_ledger_outstanding(rdt, rnm))
		doc_out = ledger_out

	pdc_total = flt(pdc_direct) + flt(pdc_via)
	remaining = get_remaining_settlement_capacity(rdt, rnm, outstanding_amount=doc_out, exclude_pdc=None)

	out = {
		"reference_doctype": rdt,
		"reference_name": rnm,
		"company": company,
		"currency": currency,
		"financial_basis_amount": gt,
		"payment_entry_amount": pe_sum,
		"effective_pdc_amount_direct": pdc_direct,
		"effective_pdc_amount_via_pr": pdc_via,
		"effective_pdc_amount": pdc_total,
		"ledger_outstanding": ledger_out,
		"document_outstanding": doc_out,
		"remaining_balance": remaining,
	}
	return out


@frappe.whitelist()
def get_pdc_settlement_summary(reference_doctype: str | None = None, reference_name: str | None = None):
	"""Desk: load settlement summary for the open document (SI / PI / Payment Request)."""
	data = get_settlement_summary_for_reference(reference_doctype, reference_name)
	if data is None:
		return {}
	return data


__all__ = [
	"get_pdc_settlement_summary",
	"get_settlement_summary_for_reference",
]
