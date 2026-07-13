from __future__ import annotations

from dataclasses import dataclass

import frappe
from frappe import _
from frappe.utils import flt

ALLOCATION_MODE_ADVANCE = "advance"
_ALLOWED_ORDERS = ("Purchase Order", "Sales Order")


@dataclass(frozen=True)
class _PDCHeader:
	name: str
	allocation_mode: str
	cheque_amount: float
	recognition_je_posted: int
	instrument_dead: int
	instrument_dead_reason: str | None


def _require_order_doctype(order_doctype: str) -> None:
	if order_doctype not in _ALLOWED_ORDERS:
		frappe.throw(
			_("Only Purchase Order or Sales Order are allowed for advance open amount queries."),
			title=_("PDC Open Advance"),
		)


def _read_pdc_header(pdc_name: str) -> _PDCHeader:
	if not pdc_name:
		frappe.throw(_("PDC name is required."), title=_("PDC Open Advance"))
	row = frappe.db.get_value(
		"Post Dated Cheque",
		pdc_name,
		[
			"name",
			"allocation_mode",
			"cheque_amount",
			"recognition_je_posted",
			"instrument_dead",
			"instrument_dead_reason",
		],
		as_dict=True,
	)
	if not row:
		frappe.throw(_("Post Dated Cheque {0} was not found.").format(pdc_name), title=_("PDC Open Advance"))
	return _PDCHeader(
		name=row.get("name") or pdc_name,
		allocation_mode=(row.get("allocation_mode") or "").strip(),
		cheque_amount=flt(row.get("cheque_amount")),
		recognition_je_posted=int(row.get("recognition_je_posted") or 0),
		instrument_dead=int(row.get("instrument_dead") or 0),
		instrument_dead_reason=(row.get("instrument_dead_reason") or None),
	)


def _require_advance_mode(h: _PDCHeader) -> None:
	if (h.allocation_mode or "").strip() != ALLOCATION_MODE_ADVANCE:
		frappe.throw(
			_("Post Dated Cheque {0} is not in advance allocation mode.").format(h.name),
			title=_("PDC Open Advance"),
		)


def _is_allocatable_advance(h: _PDCHeader) -> bool:
	"""True when this PDC can provide allocatable open advance."""
	if (h.allocation_mode or "").strip() != ALLOCATION_MODE_ADVANCE:
		return False
	if h.instrument_dead:
		return False
	# v1: recognized gross exists only after recognition JE posts.
	if not h.recognition_je_posted:
		return False
	return True


def _recognized_gross(h: _PDCHeader) -> float:
	"""v1 whole-instrument recognition: gross is cheque_amount once recognition JE is posted."""
	if not _is_allocatable_advance(h):
		return 0.0
	return flt(h.cheque_amount)


def _invoice_app_table_exists() -> bool:
	try:
		return bool(frappe.db.table_exists("tabPDC Invoice Application"))
	except Exception:
		return False


def _sum_applications_for_pdc(pdc_name: str) -> tuple[float, float]:
	"""Return (applied_amount, reversed_amount) in PDC currency for this instrument."""
	if not _invoice_app_table_exists():
		return 0.0, 0.0
	rows = frappe.db.sql(
		"""
		SELECT application_status, SUM(COALESCE(amount_in_pdc_currency, 0)) AS amt
		FROM `tabPDC Invoice Application`
		WHERE post_dated_cheque = %s
		  AND application_status IN ('posted', 'reversed')
		GROUP BY application_status
		""",
		(pdc_name,),
		as_dict=True,
	)
	applied = 0.0
	reversed = 0.0
	for r in rows or []:
		st = (r.get("application_status") or "").strip()
		amt = flt(r.get("amt"))
		if st == "posted":
			applied += amt
		elif st == "reversed":
			reversed += amt
	return applied, reversed


def _sum_applications_for_pdc_order(
	pdc_name: str, order_doctype: str, order_name: str
) -> tuple[float, float]:
	"""Return (applied_amount, reversed_amount) in PDC currency for this instrument+order bucket."""
	if not _invoice_app_table_exists():
		return 0.0, 0.0
	rows = frappe.db.sql(
		"""
		SELECT application_status, SUM(COALESCE(amount_in_pdc_currency, 0)) AS amt
		FROM `tabPDC Invoice Application`
		WHERE post_dated_cheque = %s
		  AND order_doctype = %s
		  AND order_name = %s
		  AND application_status IN ('posted', 'reversed')
		GROUP BY application_status
		""",
		(pdc_name, order_doctype, order_name),
		as_dict=True,
	)
	applied = 0.0
	reversed = 0.0
	for r in rows or []:
		st = (r.get("application_status") or "").strip()
		amt = flt(r.get("amt"))
		if st == "posted":
			applied += amt
		elif st == "reversed":
			reversed += amt
	return applied, reversed


def _sum_order_bucket_gross_from_allocations(pdc_name: str, order_doctype: str, order_name: str) -> float:
	"""Bucket gross is driven by advance-mode PDC Allocation rows (PO/SO references)."""
	row = frappe.db.sql(
		"""
		SELECT SUM(COALESCE(amount, 0)) AS amt
		FROM `tabPDC Allocation`
		WHERE parenttype = 'Post Dated Cheque'
		  AND parent = %s
		  AND allocation_mode = %s
		  AND reference_doctype = %s
		  AND reference_name = %s
		""",
		(pdc_name, ALLOCATION_MODE_ADVANCE, order_doctype, order_name),
		as_dict=True,
	)
	return flt((row[0] or {}).get("amt")) if row else 0.0


def is_pdc_advance_allocatable(pdc_name: str) -> bool:
	"""Whether this instrument can be used as an advance source (advance-mode only)."""
	h = _read_pdc_header(pdc_name)
	_require_advance_mode(h)
	return _is_allocatable_advance(h)


def get_pdc_open_advance_instrument(pdc_name: str) -> dict:
	"""Instrument-level open advance for an advance-mode PDC.

	Returns (all values in PDC currency):
	{
	  "pdc": ...,
	  "allocation_mode": "advance",
	  "recognized_gross": ...,
	  "applied_amount": ...,
	  "reversed_amount": ...,
	  "open_amount": ...,
	  "allocatable": true/false
	}
	"""
	h = _read_pdc_header(pdc_name)
	_require_advance_mode(h)

	allocatable = _is_allocatable_advance(h)
	gross = _recognized_gross(h)
	applied, reversed_amt = _sum_applications_for_pdc(h.name) if allocatable else (0.0, 0.0)
	open_amt = max(0.0, flt(gross) - flt(applied) + flt(reversed_amt)) if allocatable else 0.0

	return {
		"pdc": h.name,
		"allocation_mode": ALLOCATION_MODE_ADVANCE,
		"recognized_gross": flt(gross),
		"applied_amount": flt(applied),
		"reversed_amount": flt(reversed_amt),
		"open_amount": flt(open_amt),
		"allocatable": bool(allocatable),
	}


def get_pdc_open_advance_by_order(pdc_name: str, order_doctype: str, order_name: str) -> dict:
	"""Order bucket open advance for an advance-mode PDC (PO/SO only).

	Returns (all values in PDC currency):
	{
	  "pdc": ...,
	  "order_doctype": ...,
	  "order_name": ...,
	  "bucket_gross": ...,
	  "applied_amount": ...,
	  "reversed_amount": ...,
	  "open_amount": ...,
	  "allocatable": true/false
	}
	"""
	_require_order_doctype(order_doctype)
	if not order_name:
		frappe.throw(_("Order name is required."), title=_("PDC Open Advance"))

	h = _read_pdc_header(pdc_name)
	_require_advance_mode(h)
	allocatable = _is_allocatable_advance(h)

	# v1: when not recognized, gross is 0 so open is 0.
	bucket_gross = (
		_sum_order_bucket_gross_from_allocations(h.name, order_doctype, order_name) if allocatable else 0.0
	)
	applied, reversed_amt = (
		_sum_applications_for_pdc_order(h.name, order_doctype, order_name) if allocatable else (0.0, 0.0)
	)
	open_amt = max(0.0, flt(bucket_gross) - flt(applied) + flt(reversed_amt)) if allocatable else 0.0

	return {
		"pdc": h.name,
		"order_doctype": order_doctype,
		"order_name": order_name,
		"bucket_gross": flt(bucket_gross),
		"applied_amount": flt(applied),
		"reversed_amount": flt(reversed_amt),
		"open_amount": flt(open_amt),
		"allocatable": bool(allocatable),
	}


def get_open_advance_for_order(order_doctype: str, order_name: str) -> dict:
	"""Aggregate open advance for a single order across all allocatable advance-mode PDCs.

	Returns:
	{
	  "order_doctype": ...,
	  "order_name": ...,
	  "open_amount": ...,
	  "pdc_count": ...,
	}
	"""
	_require_order_doctype(order_doctype)
	if not order_name:
		frappe.throw(_("Order name is required."), title=_("PDC Open Advance"))

	# Find allocatable advance-mode PDCs that have a bucket for this order.
	pdc_rows = frappe.db.sql(
		"""
		SELECT
		  p.name AS pdc,
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
		GROUP BY p.name, p.cheque_amount, p.recognition_je_posted, p.instrument_dead
		""",
		(ALLOCATION_MODE_ADVANCE, order_doctype, order_name, ALLOCATION_MODE_ADVANCE),
		as_dict=True,
	)
	if not pdc_rows:
		return {"order_doctype": order_doctype, "order_name": order_name, "open_amount": 0.0, "pdc_count": 0}

	applied_map: dict[str, float] = {}
	reversed_map: dict[str, float] = {}
	if _invoice_app_table_exists():
		app_rows = frappe.db.sql(
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
			(order_doctype, order_name),
			as_dict=True,
		)
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

	total_open = 0.0
	count = 0
	for r in pdc_rows:
		pdc = (r.get("pdc") or "").strip()
		if not pdc:
			continue
		instrument_dead = int(r.get("instrument_dead") or 0)
		recognized = int(r.get("recognition_je_posted") or 0)
		if instrument_dead or not recognized:
			continue
		bucket_gross = flt(r.get("bucket_gross"))
		applied = flt(applied_map.get(pdc))
		reversed_amt = flt(reversed_map.get(pdc))
		open_amt = max(0.0, bucket_gross - applied + reversed_amt)
		total_open += open_amt
		count += 1

	return {
		"order_doctype": order_doctype,
		"order_name": order_name,
		"open_amount": flt(total_open),
		"pdc_count": count,
	}


__all__ = [
	"get_pdc_open_advance_instrument",
	"get_pdc_open_advance_by_order",
	"get_open_advance_for_order",
	"is_pdc_advance_allocatable",
]
