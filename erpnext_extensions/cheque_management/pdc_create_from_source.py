# Copyright (c) 2026, Farbod Siyahpoosh and contributors
# For license information, please see license.txt

"""Prepare a new Post Dated Cheque from Sales Invoice, Purchase Invoice, or Payment Request.

Uses :func:`~erpnext_extensions.cheque_management.pdc_settlement_summary.get_settlement_summary_for_reference`
for remaining capacity (same basis as Step 2 / Step 3). No accounting side-effects.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt

from erpnext_extensions.cheque_management.pdc_payment_request_eligibility import is_payment_request_settlement_eligible
from erpnext_extensions.cheque_management.pdc_allocation import ALLOCATION_MODE_DIRECT
from erpnext_extensions.cheque_management.pdc_settlement_capacity import SETTLEMENT_REFERENCE_DOCTYPES
from erpnext_extensions.cheque_management.pdc_settlement_summary import get_settlement_summary_for_reference


def _default_payable_cheque_pool_account(company: str | None) -> str | None:
	"""PDC Settings **default_payable_cheque_account** for ``company`` (notes-payable pool for Payable PDC)."""
	co = (company or "").strip()
	if not co:
		return None
	settings_name = frappe.db.get_value("PDC Settings", {"company": co}, "name") or co
	if not settings_name or not frappe.db.exists("PDC Settings", settings_name):
		return None
	pool = frappe.db.get_value("PDC Settings", settings_name, "default_payable_cheque_account")
	s = (pool or "").strip()
	return s or None


def _party_and_direction_from_source(source_doctype: str, source_name: str) -> dict | None:
	"""Return ``cheque_direction``, ``party_type``, ``party`` for the source document."""
	sdt = (source_doctype or "").strip()
	snm = (source_name or "").strip()
	if sdt == "Sales Invoice":
		cust = frappe.db.get_value("Sales Invoice", snm, "customer")
		if not cust:
			return None
		return {
			"cheque_direction": "Receivable",
			"party_type": "Customer",
			"party": cust,
		}
	if sdt == "Purchase Invoice":
		sup = frappe.db.get_value("Purchase Invoice", snm, "supplier")
		if not sup:
			return None
		return {
			"cheque_direction": "Payable",
			"party_type": "Supplier",
			"party": sup,
		}
	if sdt == "Payment Request":
		row = frappe.db.get_value(
			"Payment Request",
			snm,
			["payment_request_type", "party_type", "party"],
			as_dict=True,
		)
		if not row or not row.get("party_type") or not row.get("party"):
			return None
		pr_type = (row.get("payment_request_type") or "").strip()
		ch_dir = "Receivable" if pr_type == "Inward" else "Payable"
		return {
			"cheque_direction": ch_dir,
			"party_type": (row.get("party_type") or "").strip(),
			"party": (row.get("party") or "").strip(),
		}
	return None


def _allocation_child_row(
	source_doctype: str,
	source_name: str,
	amount: float,
	*,
	company: str | None = None,
	party_type: str | None = None,
	party: str | None = None,
) -> dict:
	sdt = (source_doctype or "").strip()
	snm = (source_name or "").strip()
	base = {
		"doctype": "PDC Allocation",
		"allocation_mode": ALLOCATION_MODE_DIRECT,
		"amount": amount,
		"company": company,
		"party_type": party_type,
		"party": party,
	}
	if sdt == "Sales Invoice":
		return {
			**base,
			"reference_doctype": "Sales Invoice",
			"reference_name": snm,
		}
	if sdt == "Purchase Invoice":
		return {
			**base,
			"reference_doctype": "Purchase Invoice",
			"reference_name": snm,
		}
	if sdt == "Payment Request":
		pr = frappe.db.get_value(
			"Payment Request",
			snm,
			["reference_doctype", "reference_name"],
			as_dict=True,
		)
		if (
			not pr
			or (pr.get("reference_doctype") or "").strip() not in ("Purchase Invoice", "Sales Invoice")
			or not (pr.get("reference_name") or "").strip()
		):
			raise ValueError(
				"payment_request_must_reference_invoice: Payment Request must reference a Purchase or Sales Invoice for PDC allocation."
			)
		return {
			**base,
			"reference_doctype": (pr.get("reference_doctype") or "").strip(),
			"reference_name": (pr.get("reference_name") or "").strip(),
			"source_doctype": "Payment Request",
			"source_name": snm,
		}
	raise ValueError(sdt)


def prepare_post_dated_cheque_prefill_from_source(
	source_doctype: str | None,
	source_name: str | None,
) -> dict:
	"""Build API response for opening a new Post Dated Cheque from a supported source.

	Returns keys:

	* ``can_create`` (bool)
	* ``message`` (str, optional) — user-facing when ``can_create`` is False
	* ``prefill`` (dict, optional) — pass to ``frappe.new_doc("Post Dated Cheque", prefill)``
	* ``summary`` (dict, optional) — settlement snapshot when available
	"""
	sdt = (source_doctype or "").strip()
	snm = (source_name or "").strip()

	out: dict = {"can_create": False}

	if sdt not in SETTLEMENT_REFERENCE_DOCTYPES:
		out["message"] = _("Unsupported source document type for Post Dated Cheque.")
		return out

	if not snm or not frappe.db.exists(sdt, snm):
		out["message"] = _("Source document was not found.")
		return out

	frappe.has_permission(sdt, "read", snm, throw=True)
	frappe.has_permission("Post Dated Cheque", "create", throw=True)

	if sdt == "Payment Request":
		pr_row = frappe.db.get_value(sdt, snm, ["docstatus", "workflow_state"], as_dict=True)
		if not pr_row or not is_payment_request_settlement_eligible(pr_row):
			out["message"] = _(
				"Approve this Payment Request in workflow (or submit it when no workflow applies) before creating a linked Post Dated Cheque."
			)
			return out
	else:
		docstatus = int(frappe.db.get_value(sdt, snm, "docstatus") or 0)
		if docstatus != 1:
			out["message"] = _("Submit this document before creating a linked Post Dated Cheque.")
			return out

	summary = get_settlement_summary_for_reference(sdt, snm)
	if not summary:
		out["message"] = _("Could not determine settlement details for this document.")
		return out

	# Capacity is always for the **source** document (e.g. Payment Request uses PR ``grand_total`` / PE / PDC,
	# not the linked invoice total). Prefill uses full remaining; users may lower **cheque_amount** for a
	# partial cheque — the PDC form client keeps a single allocation row aligned with **cheque_amount**.
	remaining = flt(summary.get("remaining_balance"))
	if remaining <= 1e-9:
		out["message"] = _(
			"There is no remaining settlement capacity on this document. "
			"You cannot add a Post Dated Cheque allocation against it until capacity is available."
		)
		out["summary"] = summary
		return out

	party = _party_and_direction_from_source(sdt, snm)
	if not party:
		out["message"] = _("Could not resolve party from the source document.")
		return out

	alloc_amt = remaining
	try:
		child = _allocation_child_row(
			sdt,
			snm,
			alloc_amt,
			company=summary.get("company"),
			party_type=party["party_type"],
			party=party["party"],
		)
	except ValueError:
		out["message"] = _("Payment Request must reference a Purchase or Sales Invoice for PDC allocation.")
		return out
	if flt(child.get("amount")) <= 0:
		# Debug/assertion-level safeguard: never allow a zero allocation row to be created from source prefill.
		out["message"] = _(
			"Source prefill error: computed allocation amount is zero. Please refresh and try again."
		)
		return out
	allocated_sum = flt(child.get("amount") or 0)

	prefill = {
		"company": summary.get("company"),
		"currency": summary.get("currency"),
		"allocation_mode": ALLOCATION_MODE_DIRECT,
		"cheque_direction": party["cheque_direction"],
		"party_type": party["party_type"],
		"party": party["party"],
		"reference_doctype": sdt,
		"reference_name": snm,
		"cheque_amount": alloc_amt,
		"allocations": [child],
		# Desk ``new_doc`` does not run server ``before_insert`` — set summary currency fields so the
		# form matches child rows immediately (same formulas as ``sync_pdc_allocation_summary_amounts``).
		"allocated_amount": allocated_sum,
		"unallocated_amount": flt(alloc_amt) - allocated_sum,
	}
	if (party.get("cheque_direction") or "").strip() == "Payable":
		pool = _default_payable_cheque_pool_account(summary.get("company"))
		if pool:
			prefill["account_paid_from"] = pool

	out["can_create"] = True
	out["prefill"] = prefill
	out["summary"] = summary
	out["suggested_allocation_amount"] = alloc_amt
	return out


@frappe.whitelist()
def prepare_post_dated_cheque_from_source(
	source_doctype: str | None = None,
	source_name: str | None = None,
):
	"""Desk: return prefill payload or a safe error message."""
	return prepare_post_dated_cheque_prefill_from_source(source_doctype, source_name)


__all__ = [
	"prepare_post_dated_cheque_from_source",
	"prepare_post_dated_cheque_prefill_from_source",
]
