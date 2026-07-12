# Copyright (c) 2026, Farbod Siyahpoosh and contributors
# For license information, please see license.txt

"""Payment Entry validate hook: block over-allocation vs effective Post Dated Cheque allocations."""

from __future__ import annotations

from collections import defaultdict

import frappe
from frappe.utils import flt

from erpnext_extensions.cheque_management.pdc_settlement_capacity import (
	SETTLEMENT_REFERENCE_DOCTYPES,
	get_pr_remaining_capacity,
	get_remaining_settlement_capacity,
	sum_effective_pdc_allocations_to_reference,
)


def validate_payment_entry_against_pdc_settlement(doc, method=None) -> None:
	"""``doc_events`` hook on Payment Entry ``validate``.

	Ensures allocated amounts (per reference) do not exceed remaining settlement capacity. For Sales /
	Purchase Invoice, ``outstanding_amount`` is net of submitted PE (ERPNext). For Payment Request,
	capacity uses ``grand_total - PE - PDC`` (see ``get_remaining_settlement_capacity``).
	"""
	if getattr(doc, "docstatus", 0) == 2:
		return
	if getattr(doc, "payment_type", None) == "Internal Transfer":
		return

	references = doc.get("references") or []
	if not references:
		return

	totals: defaultdict[tuple[str, str], float] = defaultdict(float)
	pr_totals: defaultdict[str, float] = defaultdict(float)
	for row in references:
		pr = (getattr(row, "payment_request", None) or "").strip()
		if pr:
			pr_totals[pr] += flt(getattr(row, "amount", None) or row.allocated_amount)
		rdt = (row.reference_doctype or "").strip()
		rnm = (row.reference_name or "").strip()
		if rdt not in SETTLEMENT_REFERENCE_DOCTYPES or not rnm:
			continue
		totals[(rdt, rnm)] += flt(getattr(row, "amount", None) or row.allocated_amount)

	# Contract: validate Payment Request allocations via PER.payment_request ceiling.
	for pr_name, alloc_sum in pr_totals.items():
		if not alloc_sum:
			continue
		capacity = get_pr_remaining_capacity(pr_name, exclude_payment_entry=doc.name)
		if alloc_sum > capacity + 1e-6:
			frappe.throw(
				frappe._(
					"Payment Entry allocation against Payment Request {0} is {1}, but remaining capacity is {2}."
				).format(pr_name, alloc_sum, max(0.0, capacity)),
				title=frappe._("Over-allocation vs Payment Request"),
			)

	for (rdt, rnm), alloc_sum in totals.items():
		if not alloc_sum:
			continue
		outstanding = flt(frappe.db.get_value(rdt, rnm, "outstanding_amount"))
		pdc_reserved = sum_effective_pdc_allocations_to_reference(rdt, rnm)
		capacity = get_remaining_settlement_capacity(
			rdt,
			rnm,
			outstanding_amount=outstanding,
			exclude_payment_entry=None,
		)
		if alloc_sum > capacity + 1e-6:
			frappe.throw(
				frappe._(
					"Payment Entry allocation against {0} {1} is {2}, but remaining capacity is {3} "
					"(reference outstanding {4}; effective Post Dated Cheque allocations {5})."
				).format(rdt, rnm, alloc_sum, max(0.0, capacity), outstanding, pdc_reserved),
				title=frappe._("Over-allocation vs Post Dated Cheque"),
			)


__all__ = ["validate_payment_entry_against_pdc_settlement"]
