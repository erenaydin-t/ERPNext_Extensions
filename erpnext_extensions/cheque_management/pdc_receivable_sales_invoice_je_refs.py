# Copyright (c) 2026, Farbod Siyahpoosh and contributors
# For license information, please see license.txt

"""Sales Invoice references on **receivable** PDC Journal Entry party (AR) lines.

ERPNext updates Sales Invoice outstanding when a Journal Entry account row posts against the
customer receivable account with ``reference_type`` / ``reference_name`` pointing at the invoice.

This mirrors the payable Purchase Invoice slice logic.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt

from erpnext_extensions.cheque_management.pdc_workflow_state_machine import CHEQUE_DIRECTION_RECEIVABLE

_EPS = 1e-6


def receivable_sales_invoice_settlement_slices(doc) -> list[tuple[str, float]] | None:
	"""Return merged (sales_invoice_name, amount) slices for the cheque, or ``None`` for legacy JE lines.

	``None`` means: do not set SI references on party rows (same as historical behaviour).

	Rules:
	- Only **Receivable** cheques are considered.
	- If there are no allocation rows, or none reference a Sales Invoice, returns ``None``.
	- Otherwise every non-zero allocation row must reference **Sales Invoice**.
	- Amounts must sum to ``doc.cheque_amount`` (company currency precision).
	"""
	if (getattr(doc, "cheque_direction", None) or "").strip() != CHEQUE_DIRECTION_RECEIVABLE:
		return None

	allocations = list(getattr(doc, "allocations", None) or [])
	if not allocations:
		return None

	slices: list[tuple[str, float]] = []
	for row in allocations:
		amt = flt(getattr(row, "amount", None) or getattr(row, "allocated_amount", None) or 0)
		if amt <= _EPS:
			continue
		rdt = (getattr(row, "reference_doctype", None) or "").strip()
		rnm = (getattr(row, "reference_name", None) or "").strip()
		if not rdt or not rnm:
			frappe.throw(
				_("Receivable PDC allocation row is missing Reference DocType or Reference Name."),
				title=_("PDC Receivable Register"),
			)
		if rdt != "Sales Invoice":
			frappe.throw(
				_(
					"Receivable PDC allocation references {0} — use Sales Invoice allocations when allocating against invoices."
				).format(rdt),
				title=_("PDC Receivable Register"),
			)
		slices.append((rnm, amt))

	if not slices:
		return None

	merged: dict[str, float] = {}
	for sinv, amt in slices:
		merged[sinv] = merged.get(sinv, 0.0) + flt(amt)

	out = [(s, flt(a)) for s, a in merged.items()]
	total = flt(sum(a for _, a in out))
	chq = flt(getattr(doc, "cheque_amount", None) or 0)
	prec = frappe.get_precision("Post Dated Cheque", "cheque_amount") or 2
	tol = max(_EPS, 0.5 / (10**prec))
	if abs(total - chq) > tol:
		frappe.throw(
			_(
				"Total allocated to Sales Invoices ({0}) must equal Cheque Amount ({1}) when posting invoice-linked settlement."
			).format(total, chq),
			title=_("PDC Receivable Register"),
		)
	return out


__all__ = [
	"receivable_sales_invoice_settlement_slices",
]

