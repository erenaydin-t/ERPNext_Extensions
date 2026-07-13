from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt

from erpnext_extensions.cheque_management.pdc_allocation import ALLOCATION_MODE_ADVANCE


def _invoice_primary_order(invoice_doctype: str, invoice_doc) -> tuple[str | None, str | None]:
	"""Infer the primary order link from invoice items.

	v1 Task 6: order-based advances are only allowed when invoice is linked to a PO/SO.
	"""
	dt = (invoice_doctype or "").strip()
	if dt == "Purchase Invoice":
		for it in getattr(invoice_doc, "items", None) or []:
			po = (getattr(it, "purchase_order", None) or "").strip()
			if po:
				return "Purchase Order", po
		return None, None
	if dt == "Sales Invoice":
		for it in getattr(invoice_doc, "items", None) or []:
			so = (getattr(it, "sales_order", None) or "").strip()
			if so:
				return "Sales Order", so
		return None, None
	return None, None


def _require_invoice_supported(dt: str) -> None:
	if dt not in ("Purchase Invoice", "Sales Invoice"):
		frappe.throw(_("Unsupported invoice type for PDC advance application."), title=_("PDC Advance"))


def get_advance_pdc_candidates_for_invoice(invoice_doctype: str, invoice_name: str) -> list[dict]:
	"""Return allocatable advance-mode PDCs for this invoice (order-based)."""
	dt = (invoice_doctype or "").strip()
	nm = (invoice_name or "").strip()
	_require_invoice_supported(dt)
	if not nm or not frappe.db.exists(dt, nm):
		frappe.throw(_("Invoice was not found."), title=_("PDC Advance"))

	inv = frappe.get_doc(dt, nm)
	order_dt, order_nm = _invoice_primary_order(dt, inv)
	if not (order_dt and order_nm):
		# v1 default: no order link => no order-based advance application.
		return []

	company = (getattr(inv, "company", None) or "").strip()
	currency = (getattr(inv, "currency", None) or "").strip()
	if dt == "Purchase Invoice":
		party_type = "Supplier"
		party = (getattr(inv, "supplier", None) or "").strip()
	else:
		party_type = "Customer"
		party = (getattr(inv, "customer", None) or "").strip()

	# Candidate gross buckets from advance allocations on PDC.
	pdc_rows = frappe.db.sql(
		"""
		SELECT
		  p.name AS pdc,
		  p.currency AS pdc_currency,
		  p.cheque_amount AS cheque_amount,
		  p.recognition_je_posted AS recognition_je_posted,
		  p.instrument_dead AS instrument_dead,
		  SUM(COALESCE(a.amount, 0)) AS bucket_gross
		FROM `tabPost Dated Cheque` p
		INNER JOIN `tabPDC Allocation` a
		  ON a.parenttype = 'Post Dated Cheque'
		 AND a.parent = p.name
		 AND a.allocation_mode = %s
		 AND a.reference_doctype = %s
		 AND a.reference_name = %s
		WHERE p.allocation_mode = %s
		  AND p.company = %s
		  AND p.party_type = %s
		  AND p.party = %s
		  AND COALESCE(p.recognition_je_posted, 0) = 1
		  AND COALESCE(p.instrument_dead, 0) = 0
		GROUP BY p.name, p.currency, p.cheque_amount, p.recognition_je_posted, p.instrument_dead
		""",
		(ALLOCATION_MODE_ADVANCE, order_dt, order_nm, ALLOCATION_MODE_ADVANCE, company, party_type, party),
		as_dict=True,
	)
	if not pdc_rows:
		return []

	# Applications already posted/reversed for this order bucket (in PDC currency).
	app_rows = (
		frappe.db.sql(
			"""
		SELECT
		  post_dated_cheque AS pdc,
		  application_status,
		  SUM(COALESCE(amount_in_pdc_currency, 0)) AS amt
		FROM `tabPDC Invoice Application`
		WHERE order_doctype = %s
		  AND order_name = %s
		  AND application_status IN ('posted', 'reversed')
		GROUP BY post_dated_cheque, application_status
		""",
			(order_dt, order_nm),
			as_dict=True,
		)
		if frappe.db.table_exists("tabPDC Invoice Application")
		else []
	)

	applied_map: dict[str, float] = {}
	reversed_map: dict[str, float] = {}
	for r in app_rows or []:
		pdc = (r.get("pdc") or "").strip()
		st = (r.get("application_status") or "").strip()
		amt = flt(r.get("amt"))
		if not pdc:
			continue
		if st == "posted":
			applied_map[pdc] = applied_map.get(pdc, 0.0) + amt
		elif st == "reversed":
			reversed_map[pdc] = reversed_map.get(pdc, 0.0) + amt

	out: list[dict] = []
	for r in pdc_rows:
		pdc = (r.get("pdc") or "").strip()
		pdc_cur = (r.get("pdc_currency") or "").strip()
		if not pdc:
			continue
		if currency and pdc_cur and currency != pdc_cur:
			# v1: FX application is deferred; do not offer mismatched currency candidates.
			continue
		bucket_gross = flt(r.get("bucket_gross"))
		applied = flt(applied_map.get(pdc))
		rev = flt(reversed_map.get(pdc))
		open_amt = max(0.0, bucket_gross - applied + rev)
		if open_amt <= 1e-9:
			continue
		out.append(
			{
				"post_dated_cheque": pdc,
				"order_doctype": order_dt,
				"order_name": order_nm,
				"pdc_currency": pdc_cur,
				"open_amount": flt(open_amt),
				"suggested_apply_amount": flt(open_amt),
				"fx_rate": 1.0,
			}
		)
	return out


@frappe.whitelist()
def get_advance_pdc_candidates(invoice_doctype: str | None = None, invoice_name: str | None = None):
	dt = (invoice_doctype or "").strip()
	nm = (invoice_name or "").strip()
	_require_invoice_supported(dt)
	if not nm or not frappe.db.exists(dt, nm):
		frappe.throw(_("Invoice was not found."), title=_("PDC Advance"))

	inv = frappe.get_doc(dt, nm)
	order_dt, order_nm = _invoice_primary_order(dt, inv)
	if not (order_dt and order_nm):
		return {
			"reason": "no_order_link",
			"message": _(
				"This invoice is not linked to a Purchase Order / Sales Order, so order-based PDC advances cannot be applied."
			),
			"candidates": [],
		}

	rows = get_advance_pdc_candidates_for_invoice(dt, nm)
	if not rows:
		return {
			"reason": "no_candidates",
			"message": _("No recognized Advance PDCs are available for this invoice’s order."),
			"candidates": [],
		}

	return {"reason": "ok", "message": "", "candidates": rows}


__all__ = ["get_advance_pdc_candidates_for_invoice", "get_advance_pdc_candidates"]
