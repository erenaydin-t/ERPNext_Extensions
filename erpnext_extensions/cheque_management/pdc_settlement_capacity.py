# Copyright (c) 2026, Farbod Siyahpoosh and contributors
# For license information, please see license.txt

"""Shared settlement capacity: Sales / Purchase Invoice and Payment Request vs PDC allocations and Payment Entry.

Used for over-allocation prevention. Does not post accounting entries.
"""

from __future__ import annotations

import frappe
from frappe.utils import flt

from erpnext.accounts.utils import QueryPaymentLedger

from erpnext_extensions.cheque_management.pdc_workflow_state_machine import (
	CHEQUE_DIRECTION_PAYABLE,
	CHEQUE_DIRECTION_RECEIVABLE,
	WORKFLOW_CLEARED,
	WORKFLOW_ISSUED,
	WORKFLOW_REGISTERED,
	WORKFLOW_RETURNED,
	normalize_workflow_state_value,
)

# References we reconcile against submitted Payment Entry + effective PDC allocations.
SETTLEMENT_REFERENCE_DOCTYPES: frozenset[str] = frozenset(
	("Sales Invoice", "Purchase Invoice", "Payment Request")
)


def _voucher_outstanding_from_payment_ledger(voucher_type: str, voucher_no: str) -> float:
	"""Return voucher outstanding amount from Payment Ledger (party account currency).

	This is the accounting source-of-truth and remains correct even if a document field is later
	synchronized for UI behaviour (e.g. to reflect PDC exposure).
	"""
	vt = (voucher_type or "").strip()
	vn = (voucher_no or "").strip()
	if not vt or not vn:
		return 0.0
	ple = QueryPaymentLedger()
	rows = ple.get_voucher_outstandings(vouchers=[frappe._dict({"voucher_type": vt, "voucher_no": vn})])
	if not rows:
		return 0.0
	# The query may return multiple rows per voucher across accounts/parties; sum outstanding for the voucher.
	total = 0.0
	for r in rows:
		# Query rows can expose both voucher_* and against_voucher_* depending on internal joins.
		if (r.get("voucher_type") or "") == vt and (r.get("voucher_no") or "") == vn:
			total += float(r.get("outstanding_in_account_currency") or 0)
		elif (r.get("against_voucher_type") or "") == vt and (r.get("against_voucher_no") or "") == vn:
			total += float(r.get("outstanding_in_account_currency") or 0)
	return float(total)


def get_invoice_ledger_outstanding(invoice_doctype: str, invoice_name: str) -> float:
	"""Ledger outstanding for Sales/Purchase Invoice (accounting truth; party account currency)."""
	dt = (invoice_doctype or "").strip()
	nm = (invoice_name or "").strip()
	if dt not in ("Sales Invoice", "Purchase Invoice") or not nm:
		return 0.0
	return float(_voucher_outstanding_from_payment_ledger(dt, nm) or 0.0)


def pdc_workflow_reserves_settlement_against_reference(cheque_direction: str | None, workflow_state: str | None) -> bool:
	"""Whether a submitted PDC's allocation rows should count against settlement capacity on SI/PI/PR.

	Excludes planning-only states and terminal / non-competing states. Aligns with Step 2 business rule:
	only allocations that represent an active settlement intent block Payment Entry.

	* Receivable: from **Registered** onward, except **Cancelled**, **Replaced**, **Returned** (business return),
	  and **Bounced** (bank path — not treated as invoice settlement reservation here).
	* Payable: **Registered** onward once register-settlement is effective (**Issued**, **Cleared**, **Returned**);
	  **Draft** is planning-only.
	"""
	d = (cheque_direction or "").strip()
	ws = normalize_workflow_state_value(workflow_state)
	if ws in ("Cancelled", "Replaced"):
		return False
	if d == CHEQUE_DIRECTION_RECEIVABLE:
		if ws == "Draft":
			return False
		if ws in ("Returned", "Bounced"):
			return False
		return True
	if d == CHEQUE_DIRECTION_PAYABLE:
		return ws in (WORKFLOW_REGISTERED, WORKFLOW_ISSUED, WORKFLOW_CLEARED, WORKFLOW_RETURNED)
	return False


def sum_payment_entry_allocations_to_payment_request(
	payment_request: str,
	*,
	exclude_payment_entry: str | None = None,
) -> float:
	"""Sum allocated amounts from **submitted** Payment Entries against one Payment Request.

	Contract: PE→PR linkage is ONLY through ``tabPayment Entry Reference.payment_request``.
	"""
	pr = (payment_request or "").strip()
	if not pr:
		return 0.0
	excl = (exclude_payment_entry or "").strip()

	conditions = [
		"pe.docstatus = 1",
		"r.payment_request = %(pr)s",
	]
	params = {"pr": pr}
	if excl:
		conditions.append("pe.name != %(excl)s")
		params["excl"] = excl

	where_clause = " AND ".join(conditions)
	row = frappe.db.sql(
		f"""
		select coalesce(sum(r.allocated_amount), 0)
		from `tabPayment Entry Reference` r
		inner join `tabPayment Entry` pe on pe.name = r.parent
		where {where_clause}
		""",
		params,
	)
	return float(row[0][0]) if row else 0.0


def sum_payment_entry_allocations_to_reference(
	reference_doctype: str,
	reference_name: str,
	*,
	company: str | None = None,
	exclude_payment_entry: str | None = None,
) -> float:
	"""Sum allocated amounts from **submitted** Payment Entries against one reference document."""
	rdt = (reference_doctype or "").strip()
	rnm = (reference_name or "").strip()
	if not rdt or not rnm or rdt not in SETTLEMENT_REFERENCE_DOCTYPES:
		return 0.0
	excl = (exclude_payment_entry or "").strip()
	co = (company or "").strip()

	conditions = [
		"r.reference_doctype = %(rdt)s",
		"r.reference_name = %(rnm)s",
		"pe.docstatus = 1",
	]
	params = {"rdt": rdt, "rnm": rnm}
	if co:
		conditions.append("pe.company = %(company)s")
		params["company"] = co
	if excl:
		conditions.append("pe.name != %(excl)s")
		params["excl"] = excl

	where_clause = " AND ".join(conditions)
	row = frappe.db.sql(
		f"""
		select coalesce(sum(r.allocated_amount), 0)
		from `tabPayment Entry Reference` r
		inner join `tabPayment Entry` pe on pe.name = r.parent
		where {where_clause}
		""",
		params,
	)
	return float(row[0][0]) if row else 0.0


def sum_effective_pdc_allocations_to_reference(
	reference_doctype: str,
	reference_name: str,
	*,
	exclude_pdc: str | None = None,
) -> float:
	"""Sum PDC allocation amounts on other (or all) cheques that reserve settlement on this reference."""
	rdt = (reference_doctype or "").strip()
	rnm = (reference_name or "").strip()
	if not rdt or not rnm or rdt not in SETTLEMENT_REFERENCE_DOCTYPES:
		return 0.0
	excl = (exclude_pdc or "").strip()

	rows = frappe.db.sql(
		"""
		select p.cheque_direction, p.workflow_state, coalesce(a.allocated_amount, 0)
		from `tabPDC Allocation` a
		inner join `tabPost Dated Cheque` p on p.name = a.parent
		where a.reference_doctype = %s and a.reference_name = %s
			and p.docstatus = 1
			and (%s = '' or p.name != %s)
		""",
		(rdt, rnm, excl, excl),
	)
	total = 0.0
	for direction, workflow_state, amt in rows:
		if pdc_workflow_reserves_settlement_against_reference(direction, workflow_state):
			total += float(amt or 0)
	return total


def sum_effective_pdc_allocations_via_payment_request_to_invoice(
	invoice_doctype: str,
	invoice_name: str,
	*,
	exclude_pdc: str | None = None,
) -> float:
	"""Sum effective PDC allocations to Payment Requests that reference a given invoice."""
	from erpnext_extensions.cheque_management.pdc_payment_request_eligibility import (
		is_payment_request_settlement_eligible,
	)

	dt = (invoice_doctype or "").strip()
	nm = (invoice_name or "").strip()
	if dt not in ("Sales Invoice", "Purchase Invoice") or not nm:
		return 0.0
	excl = (exclude_pdc or "").strip()

	rows = frappe.db.sql(
		"""
		select p.cheque_direction, p.workflow_state, coalesce(a.allocated_amount, 0),
			pr.docstatus, pr.workflow_state as pr_workflow_state
		from `tabPDC Allocation` a
		inner join `tabPost Dated Cheque` p on p.name = a.parent
		inner join `tabPayment Request` pr on pr.name = a.reference_name
		where a.reference_doctype = 'Payment Request'
			and pr.reference_doctype = %s and pr.reference_name = %s
			and p.docstatus = 1
			and (%s = '' or p.name != %s)
		""",
		(dt, nm, excl, excl),
	)
	total = 0.0
	for direction, workflow_state, amt, pr_ds, pr_ws in rows:
		pr_row = {"docstatus": pr_ds, "workflow_state": pr_ws}
		if not is_payment_request_settlement_eligible(pr_row):
			continue
		if pdc_workflow_reserves_settlement_against_reference(direction, workflow_state):
			total += float(amt or 0)
	return total


def sum_effective_pdc_direct_to_invoice(
	invoice_doctype: str,
	invoice_name: str,
	*,
	exclude_pdc: str | None = None,
) -> float:
	dt = (invoice_doctype or "").strip()
	nm = (invoice_name or "").strip()
	if dt not in ("Sales Invoice", "Purchase Invoice") or not nm:
		return 0.0
	return sum_effective_pdc_allocations_to_reference(dt, nm, exclude_pdc=exclude_pdc)


def sum_effective_pdc_via_pr_to_invoice(
	invoice_doctype: str,
	invoice_name: str,
	*,
	exclude_pdc: str | None = None,
) -> float:
	return sum_effective_pdc_allocations_via_payment_request_to_invoice(
		invoice_doctype, invoice_name, exclude_pdc=exclude_pdc
	)


def get_invoice_remaining_capacity(
	invoice_doctype: str,
	invoice_name: str,
	*,
	exclude_pdc: str | None = None,
) -> float:
	"""Remaining settlement capacity for new allocations against an invoice.

	Contract: ledger outstanding minus effective PDC exposure (direct + via PR).
	"""
	dt = (invoice_doctype or "").strip()
	nm = (invoice_name or "").strip()
	if dt not in ("Sales Invoice", "Purchase Invoice") or not nm:
		return 0.0
	ledger_out = flt(get_invoice_ledger_outstanding(dt, nm))
	pdc_direct = flt(sum_effective_pdc_direct_to_invoice(dt, nm, exclude_pdc=exclude_pdc))
	pdc_via_pr = flt(sum_effective_pdc_via_pr_to_invoice(dt, nm, exclude_pdc=exclude_pdc))
	return flt(ledger_out - pdc_direct - pdc_via_pr)


def get_pr_remaining_capacity(
	payment_request: str,
	*,
	exclude_pdc: str | None = None,
	exclude_payment_entry: str | None = None,
) -> float:
	"""Remaining settlement capacity for new allocations against a Payment Request."""
	from erpnext_extensions.cheque_management.pdc_payment_request_eligibility import is_payment_request_settlement_eligible

	pr = (payment_request or "").strip()
	if not pr or not frappe.db.exists("Payment Request", pr):
		return 0.0
	row = frappe.db.get_value(
		"Payment Request", pr, ["grand_total", "docstatus", "workflow_state"], as_dict=True
	)
	if not row or not is_payment_request_settlement_eligible(row):
		return 0.0
	gt = flt(row.grand_total)
	pe_sum = flt(sum_payment_entry_allocations_to_payment_request(pr, exclude_payment_entry=exclude_payment_entry))
	pdc_sum = flt(sum_effective_pdc_allocations_to_reference("Payment Request", pr, exclude_pdc=exclude_pdc))
	return flt(gt - pe_sum - pdc_sum)


def sum_submitted_pr_totals_for_invoice(
	invoice_doctype: str,
	invoice_name: str,
	*,
	exclude_pr: str | None = None,
) -> float:
	"""Sum Payment Request ``grand_total`` for rows that count toward the invoice issuance ceiling.

	Uses workflow-aware eligibility (see :func:`~erpnext_extensions.cheque_management.pdc_payment_request_eligibility.pr_row_counts_toward_invoice_issuance_ceiling`).
	"""
	from erpnext_extensions.cheque_management.pdc_payment_request_eligibility import (
		pr_row_counts_toward_invoice_issuance_ceiling,
	)

	dt = (invoice_doctype or "").strip()
	nm = (invoice_name or "").strip()
	if dt not in ("Sales Invoice", "Purchase Invoice") or not nm:
		return 0.0
	excl = (exclude_pr or "").strip()
	conditions = [
		"reference_doctype = %(dt)s",
		"reference_name = %(nm)s",
	]
	params = {"dt": dt, "nm": nm}
	if excl:
		conditions.append("name != %(excl)s")
		params["excl"] = excl
	where_clause = " AND ".join(conditions)
	rows = frappe.db.sql(
		f"""
		select name, docstatus, workflow_state, grand_total
		from `tabPayment Request`
		where {where_clause}
		""",
		params,
		as_dict=True,
	)
	total = 0.0
	for r in rows or []:
		if pr_row_counts_toward_invoice_issuance_ceiling(r):
			total += float(flt(r.get("grand_total")))
	return total


def get_invoice_total_basis(invoice_doctype: str, invoice_name: str) -> float:
	"""Invoice total basis in party account currency, matching ERPNext ``set_status`` logic."""
	dt = (invoice_doctype or "").strip()
	nm = (invoice_name or "").strip()
	if dt not in ("Sales Invoice", "Purchase Invoice") or not nm:
		return 0.0
	doc = frappe.get_doc(dt, nm)
	# Import locally to avoid circular import at module load.
	if dt == "Sales Invoice":
		from erpnext.accounts.doctype.sales_invoice.sales_invoice import get_total_in_party_account_currency
	else:
		from erpnext.accounts.doctype.purchase_invoice.purchase_invoice import get_total_in_party_account_currency
	return float(flt(get_total_in_party_account_currency(doc)))


def validate_invoice_pr_issuance_ceiling(doc, method=None) -> None:
	"""Block Payment Request totals above invoice total basis when the PR counts as issued.

	Callers should invoke this only for settlement-eligible Payment Requests (see
	``validate_payment_request_invoice_ceiling_on_save``)."""
	if not doc or getattr(doc, "doctype", None) != "Payment Request":
		return
	rdt = (getattr(doc, "reference_doctype", None) or "").strip()
	rnm = (getattr(doc, "reference_name", None) or "").strip()
	if rdt not in ("Sales Invoice", "Purchase Invoice") or not rnm:
		return
	# Hard policy: do not allow PR issuance against return invoices.
	if int(frappe.db.get_value(rdt, rnm, "is_return") or 0) == 1:
		frappe.throw(
			frappe._("Payment Request cannot be submitted against a return invoice ({0} {1}).").format(rdt, rnm),
			title=frappe._("Payment Request"),
		)
	inv_total = flt(get_invoice_total_basis(rdt, rnm))
	other = flt(sum_submitted_pr_totals_for_invoice(rdt, rnm, exclude_pr=getattr(doc, "name", None)))
	this_amt = flt(getattr(doc, "grand_total", None) or 0)
	precision = frappe.get_precision("Payment Request", "grand_total") or 2
	eps = 0.5 / (10**precision)
	if other + this_amt > inv_total + eps:
		frappe.throw(
			frappe._(
				"Total Payment Requests counted against {0} {1} would be {2}, which exceeds the invoice total basis {3}."
			).format(rdt, rnm, flt(other + this_amt, precision), flt(inv_total, precision)),
			title=frappe._("Payment Request"),
		)


def get_remaining_settlement_capacity(
	reference_doctype: str,
	reference_name: str,
	*,
	outstanding_amount: float,
	exclude_pdc: str | None = None,
	exclude_payment_entry: str | None = None,
) -> float:
	"""Return amount still available for new PDC or PE allocation against this reference.

	* **Sales / Purchase Invoice:** ``remaining = ledger_outstanding - effective_pdc`` where
	  ``ledger_outstanding`` comes from Payment Ledger (accounting source-of-truth). The ``outstanding_amount``
	  argument is ignored so PDC is never subtracted twice if an app synchronizes the field for UI behaviour.
	  Pass ``exclude_pdc`` when validating rows on the same Post Dated Cheque.

	* **Payment Request:** ``remaining = grand_total - submitted_pe - effective_pdc`` (same decomposition as
	  :mod:`~erpnext_extensions.cheque_management.pdc_payment_request_status`). The ``outstanding_amount``
	  argument is **ignored** for Payment Request so PDC is not subtracted twice once the PR field holds
	  ``grand_total - PE - PDC``. Pass ``exclude_payment_entry`` when validating a **Payment Entry** that is
	  not yet submitted (so its allocations are not in the submitted sum).
	"""
	rdt = (reference_doctype or "").strip()
	rnm = (reference_name or "").strip()
	if not rdt or not rnm or rdt not in SETTLEMENT_REFERENCE_DOCTYPES:
		return flt(outstanding_amount)

	if rdt == "Payment Request":
		return get_pr_remaining_capacity(
			rnm,
			exclude_pdc=exclude_pdc,
			exclude_payment_entry=exclude_payment_entry,
		)

	if rdt in ("Sales Invoice", "Purchase Invoice"):
		return get_invoice_remaining_capacity(rdt, rnm, exclude_pdc=exclude_pdc)

	pdc_sum = sum_effective_pdc_allocations_to_reference(rdt, rnm, exclude_pdc=exclude_pdc)
	return flt(outstanding_amount) - flt(pdc_sum)


__all__ = [
	"SETTLEMENT_REFERENCE_DOCTYPES",
	"get_invoice_ledger_outstanding",
	"get_invoice_remaining_capacity",
	"get_invoice_total_basis",
	"get_pr_remaining_capacity",
	"get_remaining_settlement_capacity",
	"pdc_workflow_reserves_settlement_against_reference",
	"sum_effective_pdc_allocations_via_payment_request_to_invoice",
	"sum_effective_pdc_allocations_to_reference",
	"sum_effective_pdc_direct_to_invoice",
	"sum_effective_pdc_via_pr_to_invoice",
	"sum_payment_entry_allocations_to_payment_request",
	"sum_payment_entry_allocations_to_reference",
	"sum_submitted_pr_totals_for_invoice",
	"validate_invoice_pr_issuance_ceiling",
]
