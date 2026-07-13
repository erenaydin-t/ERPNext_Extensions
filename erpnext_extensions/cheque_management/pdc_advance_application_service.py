from __future__ import annotations

"""Service layer for Advance PDC application on invoices (PI/SI).

This module is intentionally introduced as a *contract-first* skeleton.

Implementation constraints (must remain true when filled in):
- Advance (`allocation_mode="advance"`) is strictly separate from direct settlement.
- `advance_scope` is explicit: `order_based` vs `general`; never infer scope from nullable fields.
- No Journal Entry (JE) posting before invoice submit.
- On submit/cancel: JE posting and application-row persistence must be atomic (one DB transaction).
- Concurrency protection is mandatory (locks + recompute + final checks before JE).
"""

from dataclasses import dataclass
from typing import Any, Literal, TypedDict

import frappe
from frappe import _
from frappe.utils import flt

from erpnext_extensions.cheque_management.pdc_open_advance import (
	get_open_advance_for_order,
	get_pdc_open_advance_by_order,
	get_pdc_open_advance_instrument,
)

AdvanceScope = Literal["order_based", "general"]
ResourceType = Literal["instrument", "order_bucket"]


class CandidateRow(TypedDict, total=False):
	"""Single candidate record returned to Desk.

	All rows must be scope-tagged to prevent UI mixing.
	"""

	candidate_id: str
	post_dated_cheque: str
	allocation_mode: str  # always "advance" here
	advance_scope: AdvanceScope

	# Order-based only
	source_doctype: str | None
	source_name: str | None

	# General only
	pool_key: dict[str, Any] | None

	pdc_currency: str | None
	invoice_currency: str | None
	open_amount: float
	suggested_apply_amount: float
	fx_rate: float
	recognition_je_posted: int | None
	instrument_dead: int | None


class CandidatesResponse(TypedDict, total=False):
	company: str
	party_type: str
	party: str
	invoice_doctype: str
	invoice_name: str
	currency: str | None
	order_link: dict[str, str] | None
	candidates: list[CandidateRow]
	reason: str
	message: str


@dataclass(frozen=True)
class NormalizedApplicationRow:
	"""A normalized draft invoice application row, ready for planning/validation."""

	row_name: str
	post_dated_cheque: str
	advance_scope: AdvanceScope
	amount: float
	amount_in_pdc_currency: float
	fx_rate: float
	order_doctype: str | None = None
	order_name: str | None = None


@dataclass(frozen=True)
class ResourceKey:
	"""Key for a consumable resource."""

	type: ResourceType
	post_dated_cheque: str
	order_doctype: str | None = None
	order_name: str | None = None


@dataclass(frozen=True)
class ResourceDemand:
	"""Requested consumption against a single resource."""

	key: ResourceKey
	advance_scope: AdvanceScope
	requested_amount: float


@dataclass(frozen=True)
class ConsumptionPlan:
	"""Computed plan derived from draft rows (no DB effects)."""

	invoice_doctype: str
	invoice_name: str
	currency: str | None
	total_requested: float
	by_resource: tuple[ResourceDemand, ...]


def validate_pdc_invoice_application_rows_structural(invoice_doc) -> None:
	"""Lightweight structural validation for draft invoice `pdc_invoice_applications` rows.

	This is intentionally **not** an open-balance check. It enforces only row shape and
	scope consistency so drafts can be saved safely without affecting the current working
	order-based flow.

	Rules:
	- Only validates while invoice is in Draft (`docstatus == 0`).
	- For rows that are `application_status == "draft"` (or blank):
	  - `post_dated_cheque` must be present and exist.
	  - `amount` must be > 0.
	  - `advance_scope` must be `order_based` or `general`.
	    Backward compatibility: if `advance_scope` is blank and order fields exist, treat as `order_based`.
	  - If scope is `order_based`: `order_doctype` and `order_name` must be present.
	  - If scope is `general`: `order_doctype` and `order_name` must be empty.

	Must never:
	- Query or compute open balances.
	- Post Journal Entries.
	- Mutate database state.
	"""
	if not invoice_doc:
		return
	docstatus = int(getattr(invoice_doc, "docstatus", 0) or 0)
	if docstatus != 0:
		return

	rows = list(getattr(invoice_doc, "pdc_invoice_applications", None) or [])
	if not rows:
		return

	for r in rows:
		st = (getattr(r, "application_status", None) or "draft").strip()
		if st != "draft":
			continue

		pdc = (getattr(r, "post_dated_cheque", None) or "").strip()
		if not pdc:
			frappe.throw(_("PDC Invoice Application: Post Dated Cheque is required."), title=_("PDC Advance"))
		if not frappe.db.exists("Post Dated Cheque", pdc):
			frappe.throw(
				_("PDC Invoice Application: Post Dated Cheque {0} was not found.").format(pdc),
				title=_("PDC Advance"),
			)

		amt = flt(getattr(r, "amount", None) or 0)
		if amt <= 0:
			frappe.throw(_("PDC Invoice Application: Amount must be > 0."), title=_("PDC Advance"))

		def _norm_empty(v) -> str:
			if v is None:
				return ""
			s = str(v).strip()
			if not s:
				return ""
			low = s.lower()
			return "" if low in ("null", "undefined", "none") else s

		odt_raw = getattr(r, "order_doctype", None)
		onm_raw = getattr(r, "order_name", None)
		odt = _norm_empty(odt_raw)
		onm = _norm_empty(onm_raw)

		scope_raw = (getattr(r, "advance_scope", None) or "").strip()
		if not scope_raw:
			# Compatibility default: existing rows are order-based and have order fields.
			scope_raw = "order_based" if (odt or onm) else "general"

		if scope_raw not in ("order_based", "general"):
			frappe.throw(
				_("PDC Invoice Application: Advance Scope must be order_based or general."),
				title=_("PDC Advance"),
			)

		if scope_raw == "order_based":
			if not odt or not onm:
				frappe.throw(
					_(
						"PDC Invoice Application: Order DocType and Order are required for order_based advances."
					),
					title=_("PDC Advance"),
				)
		else:
			if odt or onm:
				frappe.throw(
					_(
						"PDC Invoice Application: General advance rows must have empty order fields. "
						"Got order_doctype={0}, order_name={1}."
					).format(repr(odt_raw), repr(onm_raw)),
					title=_("PDC Advance"),
				)


def get_advance_candidates_for_invoice(
	invoice_doctype: str,
	invoice_name: str,
	*,
	include_general: bool = True,
) -> CandidatesResponse:
	"""Return a flat, scope-tagged list of allocatable advance candidates for an invoice.

	Responsibilities:
	- Determine invoice party/company/currency and optional order link.
	- Return candidates from order-based pool (when invoice has PO/SO link).
	- Return candidates from general pool (when include_general=True and eligible).
	- Never mix scopes: every candidate row must include `advance_scope` and a stable `candidate_id`.

	Must never:
	- Post JEs.
	- Mutate invoice or PDC documents.
	- Return unrecognized/dead instruments.
	"""
	dt = (invoice_doctype or "").strip()
	nm = (invoice_name or "").strip()
	if dt not in ("Purchase Invoice", "Sales Invoice"):
		frappe.throw(_("Unsupported invoice type for PDC advance application."), title=_("PDC Advance"))
	if not nm or not frappe.db.exists(dt, nm):
		frappe.throw(_("Invoice was not found."), title=_("PDC Advance"))

	inv = frappe.get_doc(dt, nm)
	company = (getattr(inv, "company", None) or "").strip()
	currency = (getattr(inv, "currency", None) or "").strip()
	grand_total = flt(getattr(inv, "grand_total", None) or 0)
	if dt == "Purchase Invoice":
		party_type = "Supplier"
		party = (getattr(inv, "supplier", None) or "").strip()
		order_field = "purchase_order"
		order_dt = "Purchase Order"
	else:
		party_type = "Customer"
		party = (getattr(inv, "customer", None) or "").strip()
		order_field = "sales_order"
		order_dt = "Sales Order"

	order_nm: str | None = None
	for it in getattr(inv, "items", None) or []:
		val = (getattr(it, order_field, None) or "").strip()
		if val:
			order_nm = val
			break

	order_link = {"order_doctype": order_dt if order_nm else None, "order_name": order_nm or None}

	out: CandidatesResponse = {
		"invoice_doctype": dt,
		"invoice_name": nm,
		"company": company,
		"party_type": party_type,
		"party": party,
		"currency": currency,
		"order_link": order_link,
		"candidates": [],
		"reason": "ok",
		"message": "",
	}

	# -------------------------
	# A) order_based candidates
	# -------------------------
	if order_nm:
		rows = frappe.db.sql(
			"""
			SELECT
			  p.name AS pdc,
			  p.currency AS pdc_currency,
			  COALESCE(p.advance_scope, 'order_based') AS advance_scope,
			  COALESCE(p.recognition_je_posted, 0) AS recognition_je_posted,
			  COALESCE(p.instrument_dead, 0) AS instrument_dead
			FROM `tabPost Dated Cheque` p
			INNER JOIN `tabPDC Allocation` a
			  ON a.parenttype = 'Post Dated Cheque'
			 AND a.parent = p.name
			 AND COALESCE(a.allocation_mode, 'advance') = 'advance'
			 AND a.reference_doctype = %(order_dt)s
			 AND a.reference_name = %(order_nm)s
			WHERE COALESCE(p.allocation_mode, 'direct_settlement') = 'advance'
			  AND COALESCE(p.advance_scope, 'order_based') IN ('order_based', '')
			  AND p.company = %(company)s
			  AND p.party_type = %(party_type)s
			  AND p.party = %(party)s
			  AND COALESCE(p.recognition_je_posted, 0) = 1
			  AND COALESCE(p.instrument_dead, 0) = 0
			  AND p.docstatus = 1
			  AND IFNULL(p.workflow_state, '') NOT IN ('Cancelled', 'Replaced')
			GROUP BY p.name, p.currency, p.advance_scope, p.recognition_je_posted, p.instrument_dead
			""",
			{
				"order_dt": order_dt,
				"order_nm": order_nm,
				"company": company,
				"party_type": party_type,
				"party": party,
			},
			as_dict=True,
		)
		for r in rows or []:
			pdc = (r.get("pdc") or "").strip()
			pdc_cur = (r.get("pdc_currency") or "").strip()
			if not pdc:
				continue
			# v1 currency: only same-currency candidates.
			if currency and pdc_cur and currency != pdc_cur:
				# v1: multi-currency application is intentionally deferred.
				continue
			oa = get_pdc_open_advance_by_order(pdc, order_dt, order_nm)
			open_amt = flt(oa.get("open_amount"))
			if open_amt <= 1e-9:
				continue
			out["candidates"].append(
				{
					"candidate_id": f"order_based:{pdc}:{order_dt}:{order_nm}",
					"post_dated_cheque": pdc,
					"allocation_mode": "advance",
					"advance_scope": "order_based",
					"source_doctype": order_dt,
					"source_name": order_nm,
					"pool_key": None,
					"pdc_currency": pdc_cur,
					"invoice_currency": currency,
					"open_amount": open_amt,
					"suggested_apply_amount": open_amt,
					"fx_rate": 1.0,
					"recognition_je_posted": 1,
					"instrument_dead": 0,
				}
			)

	# ----------------------
	# B) general candidates
	# ----------------------
	if include_general:
		rows = frappe.db.sql(
			"""
			SELECT
			  p.name AS pdc,
			  p.currency AS pdc_currency,
			  COALESCE(p.advance_scope, 'order_based') AS advance_scope,
			  COALESCE(p.recognition_je_posted, 0) AS recognition_je_posted,
			  COALESCE(p.instrument_dead, 0) AS instrument_dead
			FROM `tabPost Dated Cheque` p
			WHERE COALESCE(p.allocation_mode, 'direct_settlement') = 'advance'
			  AND COALESCE(p.advance_scope, 'order_based') = 'general'
			  AND p.company = %(company)s
			  AND p.party_type = %(party_type)s
			  AND p.party = %(party)s
			  AND COALESCE(p.recognition_je_posted, 0) = 1
			  AND COALESCE(p.instrument_dead, 0) = 0
			  AND p.docstatus = 1
			  AND IFNULL(p.workflow_state, '') NOT IN ('Cancelled', 'Replaced')
			  AND NOT EXISTS (
				SELECT 1
				FROM `tabPDC Allocation` a
				WHERE a.parenttype = 'Post Dated Cheque'
				  AND a.parent = p.name
			  )
			""",
			{"company": company, "party_type": party_type, "party": party},
			as_dict=True,
		)
		for r in rows or []:
			pdc = (r.get("pdc") or "").strip()
			pdc_cur = (r.get("pdc_currency") or "").strip()
			if not pdc:
				continue
			if currency and pdc_cur and currency != pdc_cur:
				# v1: multi-currency application is intentionally deferred.
				continue
			oa = get_pdc_open_advance_instrument(pdc)
			open_amt = flt(oa.get("open_amount"))
			if open_amt <= 1e-9:
				continue
			out["candidates"].append(
				{
					"candidate_id": f"general:{pdc}",
					"post_dated_cheque": pdc,
					"allocation_mode": "advance",
					"advance_scope": "general",
					"source_doctype": None,
					"source_name": None,
					"pool_key": {
						"company": company,
						"party_type": party_type,
						"party": party,
						"currency": currency,
						"dim_set": {},
					},
					"pdc_currency": pdc_cur,
					"invoice_currency": currency,
					"open_amount": open_amt,
					"suggested_apply_amount": open_amt,
					"fx_rate": 1.0,
					"recognition_je_posted": 1,
					"instrument_dead": 0,
				}
			)

	# -------------------------
	# Mixed-pool suggestion rule
	# -------------------------
	# Default suggestion policy: order_based first, then general from remaining invoice amount.
	# Never suggest more than invoice grand_total.
	remaining = flt(grand_total)
	suggested: list[CandidateRow] = []
	for c in out["candidates"] or []:
		open_amt = flt(c.get("open_amount"))
		if open_amt <= 1e-9 or remaining <= 1e-9:
			continue
		sug = min(open_amt, remaining)
		if sug <= 1e-9:
			continue
		c["suggested_apply_amount"] = flt(sug)
		remaining -= flt(sug)
		suggested.append(c)
	out["candidates"] = suggested

	if not out["candidates"]:
		out["reason"] = "no_candidates"
		out["message"] = _("No recognized Advance PDCs are available for this invoice.")

	return out


@frappe.whitelist()
def get_advance_candidates_for_invoice_api(
	invoice_doctype: str | None = None,
	invoice_name: str | None = None,
	include_general: int | str | None = 1,
) -> CandidatesResponse:
	"""Whitelisted wrapper for Desk calls.

	Read-only: returns candidates only; no side effects.
	"""
	inc = str(include_general).strip().lower() not in ("0", "false", "no", "")
	return get_advance_candidates_for_invoice(invoice_doctype or "", invoice_name or "", include_general=inc)


def normalize_invoice_pdc_application_rows(invoice_doc) -> list[NormalizedApplicationRow]:
	"""Normalize draft `pdc_invoice_applications` rows on an invoice.

	Responsibilities:
	- Extract draft rows only.
	- Enforce structural invariants (required fields, scope-specific fields).
	- Enforce invoice header compatibility (company/party/currency/order link constraints).

	Must never:
	- Perform open-balance checks (submit-time only).
	- Post JEs.
	- Acquire locks.
	"""
	if not invoice_doc:
		return []
	docstatus = int(getattr(invoice_doc, "docstatus", 0) or 0)
	if docstatus != 0:
		return []

	dt = (getattr(invoice_doc, "doctype", None) or "").strip()
	if dt not in ("Purchase Invoice", "Sales Invoice"):
		return []

	company = (getattr(invoice_doc, "company", None) or "").strip()
	currency = (getattr(invoice_doc, "currency", None) or "").strip()

	if dt == "Purchase Invoice":
		party_type = "Supplier"
		party = (getattr(invoice_doc, "supplier", None) or "").strip()
		order_field = "purchase_order"
		order_dt = "Purchase Order"
	else:
		party_type = "Customer"
		party = (getattr(invoice_doc, "customer", None) or "").strip()
		order_field = "sales_order"
		order_dt = "Sales Order"

	order_nm: str | None = None
	for it in getattr(invoice_doc, "items", None) or []:
		val = (getattr(it, order_field, None) or "").strip()
		if val:
			order_nm = val
			break

	out: list[NormalizedApplicationRow] = []
	rows = list(getattr(invoice_doc, "pdc_invoice_applications", None) or [])
	for r in rows:
		st = (getattr(r, "application_status", None) or "draft").strip()
		if st not in ("", "draft"):
			continue

		row_name = (getattr(r, "name", None) or "").strip() or "(new row)"
		pdc = (getattr(r, "post_dated_cheque", None) or "").strip()
		if not pdc:
			frappe.throw(
				_("Row {0}: Post Dated Cheque is required.").format(row_name),
				title=_("PDC Advance"),
			)
		if not frappe.db.exists("Post Dated Cheque", pdc):
			frappe.throw(
				_("Row {0}: Post Dated Cheque {1} was not found.").format(row_name, pdc),
				title=_("PDC Advance"),
			)

		scope = (getattr(r, "advance_scope", None) or "").strip()
		if scope not in ("order_based", "general"):
			frappe.throw(
				_("Row {0}: Advance Scope must be order_based or general.").format(row_name),
				title=_("PDC Advance"),
			)

		amt = flt(getattr(r, "amount", None) or 0)
		if amt <= 0:
			frappe.throw(
				_("Row {0}: Amount must be > 0.").format(row_name),
				title=_("PDC Advance"),
			)

		amt_pdc = flt(getattr(r, "amount_in_pdc_currency", None) or 0)
		fx_rate = flt(getattr(r, "fx_rate", None) or 1.0) or 1.0
		if amt_pdc <= 0:
			# v1 same-currency only; the posting flow uses amount_in_pdc_currency as canonical.
			frappe.throw(
				_("Row {0}: Amount (PDC Currency) must be > 0.").format(row_name),
				title=_("PDC Advance"),
			)

		odt = (getattr(r, "order_doctype", None) or "").strip() or None
		onm = (getattr(r, "order_name", None) or "").strip() or None

		# Scope rule (row shape + invoice order link)
		if scope == "order_based":
			if not order_nm:
				frappe.throw(
					_("Row {0}: Order-based advance requires this invoice to be linked to a {1}.").format(
						row_name, order_dt
					),
					title=_("PDC Advance"),
				)
			if not odt or not onm:
				frappe.throw(
					_("Row {0}: Order DocType and Order are required for order_based advances.").format(
						row_name
					),
					title=_("PDC Advance"),
				)
			if odt != order_dt or onm != order_nm:
				frappe.throw(
					_(
						"Row {0}: Order-based advance rows must match the invoice order link ({1} {2})."
					).format(row_name, order_dt, order_nm),
					title=_("PDC Advance"),
				)
		else:
			# general
			if odt or onm:
				frappe.throw(
					_("Row {0}: General advance cannot have order fields.").format(row_name),
					title=_("PDC Advance"),
				)

		# Eligibility checks against PDC header (read-only)
		p = (
			frappe.db.get_value(
				"Post Dated Cheque",
				pdc,
				[
					"docstatus",
					"allocation_mode",
					"advance_scope",
					"recognition_je_posted",
					"instrument_dead",
					"workflow_state",
					"company",
					"party_type",
					"party",
					"currency",
				],
				as_dict=True,
			)
			or {}
		)

		if int(p.get("docstatus") or 0) != 1:
			frappe.throw(
				_("Row {0}: PDC {1} must be submitted.").format(row_name, pdc), title=_("PDC Advance")
			)
		if (p.get("allocation_mode") or "").strip() != "advance":
			frappe.throw(
				_("Row {0}: PDC {1} is not in advance mode.").format(row_name, pdc), title=_("PDC Advance")
			)
		if int(p.get("recognition_je_posted") or 0) != 1:
			frappe.throw(
				_("Row {0}: PDC {1} is not recognized yet.").format(row_name, pdc), title=_("PDC Advance")
			)
		if int(p.get("instrument_dead") or 0) == 1:
			frappe.throw(_("Row {0}: PDC {1} is dead.").format(row_name, pdc), title=_("PDC Advance"))
		if (p.get("workflow_state") or "").strip() in ("Cancelled", "Replaced"):
			frappe.throw(
				_("Row {0}: PDC {1} is cancelled/replaced.").format(row_name, pdc), title=_("PDC Advance")
			)

		if (p.get("company") or "").strip() != company:
			frappe.throw(_("Row {0}: PDC company mismatch.").format(row_name), title=_("PDC Advance"))
		if (p.get("party_type") or "").strip() != party_type or (p.get("party") or "").strip() != party:
			frappe.throw(_("Row {0}: PDC party mismatch.").format(row_name), title=_("PDC Advance"))
		if (p.get("currency") or "").strip() != currency:
			frappe.throw(
				_(
					"Multi-currency PDC advance application is not supported yet. "
					"PDC currency must match invoice currency."
				),
				title=_("PDC Advance"),
			)

		p_scope = (p.get("advance_scope") or "").strip()
		if scope == "order_based":
			if p_scope not in ("", "order_based"):
				frappe.throw(
					_("Row {0}: PDC {1} is not order-based.").format(row_name, pdc), title=_("PDC Advance")
				)
		else:
			# general
			if p_scope != "general":
				frappe.throw(
					_("Row {0}: PDC {1} is not general advance.").format(row_name, pdc),
					title=_("PDC Advance"),
				)
			# General PDC must have no allocation rows
			if frappe.db.exists("PDC Allocation", {"parenttype": "Post Dated Cheque", "parent": pdc}):
				frappe.throw(
					_("Row {0}: General advance PDC must not have allocation rows.").format(row_name),
					title=_("PDC Advance"),
				)

		out.append(
			NormalizedApplicationRow(
				row_name=row_name,
				post_dated_cheque=pdc,
				advance_scope=scope,  # explicit only
				amount=amt,
				amount_in_pdc_currency=amt_pdc,
				fx_rate=fx_rate,
				order_doctype=odt,
				order_name=onm,
			)
		)

	return out


def build_consumption_plan(invoice_doc, rows: list[NormalizedApplicationRow]) -> ConsumptionPlan:
	"""Build a consumption plan (grouped by resources) from normalized rows.

	Responsibilities:
	- Produce per-resource demands:
	  - instrument resources for all rows
	  - order_bucket resources for order_based rows
	- Compute invoice total requested (invoice currency in v1).

	Must never:
	- Read/write the database.
	- Post JEs.
	"""
	if not invoice_doc:
		frappe.throw(_("Invoice document is required."), title=_("PDC Advance"))
	dt = (getattr(invoice_doc, "doctype", None) or "").strip()
	nm = (getattr(invoice_doc, "name", None) or "").strip()
	currency = (getattr(invoice_doc, "currency", None) or "").strip() or None

	total = 0.0
	by_instrument: dict[str, float] = {}
	by_bucket: dict[tuple[str, str, str], float] = {}
	for r in rows or []:
		total += flt(r.amount_in_pdc_currency)
		by_instrument[r.post_dated_cheque] = by_instrument.get(r.post_dated_cheque, 0.0) + flt(
			r.amount_in_pdc_currency
		)
		if r.advance_scope == "order_based":
			if not (r.order_doctype and r.order_name):
				frappe.throw(_("Order-based row is missing order key."), title=_("PDC Advance"))
			k = (r.post_dated_cheque, r.order_doctype, r.order_name)
			by_bucket[k] = by_bucket.get(k, 0.0) + flt(r.amount_in_pdc_currency)

	demands: list[ResourceDemand] = []
	for pdc, amt in sorted(by_instrument.items()):
		# Instrument-level demand exists for both scopes; scope-specific enforcement is done upstream
		# during normalization (PDC advance_scope checks). Keep the demand type stable.
		demands.append(
			ResourceDemand(
				key=ResourceKey(type="instrument", post_dated_cheque=pdc),
				advance_scope="general",
				requested_amount=flt(amt),
			)
		)
	for (pdc, odt, onm), amt in sorted(by_bucket.items()):
		demands.append(
			ResourceDemand(
				key=ResourceKey(
					type="order_bucket", post_dated_cheque=pdc, order_doctype=odt, order_name=onm
				),
				advance_scope="order_based",
				requested_amount=flt(amt),
			)
		)

	return ConsumptionPlan(
		invoice_doctype=dt,
		invoice_name=nm,
		currency=currency,
		total_requested=flt(total),
		by_resource=tuple(demands),
	)


def lock_consumption_resources(plan: ConsumptionPlan) -> None:
	"""Acquire DB locks for all resources in this plan.

	Transactional requirement:
	- Must be called inside the invoice submit/cancel DB transaction.
	- Locks must be acquired in deterministic order to avoid deadlocks.

	Must never:
	- Post JEs.
	- Commit the transaction.
	"""
	raise NotImplementedError


def recompute_canonical_opens(plan: ConsumptionPlan) -> dict[ResourceKey, float]:
	"""Recompute canonical open amounts for each resource under lock.

	Canonical truth (when implemented):
	- Recognition + instrument-dead flags gate gross.
	- Consumption/restoration must be derived from posted application JEs (and/or a guaranteed-consistent registry).

	Must never:
	- Use draft invoice rows as truth.
	- Post JEs.
	"""
	opens: dict[ResourceKey, float] = {}
	for d in plan.by_resource or ():
		k = d.key
		if k.type == "instrument":
			oa = get_pdc_open_advance_instrument(k.post_dated_cheque)
			opens[k] = flt(oa.get("open_amount"))
		elif k.type == "order_bucket":
			oa = get_pdc_open_advance_by_order(k.post_dated_cheque, k.order_doctype or "", k.order_name or "")
			opens[k] = flt(oa.get("open_amount"))
	return opens


def validate_consumption_plan(invoice_doc, plan: ConsumptionPlan, opens: dict[ResourceKey, float]) -> None:
	"""Validate that the plan is safe to apply.

	Required invariants:
	- sum(requested) <= invoice grand_total
	- per-instrument: requested <= open
	- per-order-bucket (order_based): requested <= open
	- reject scope mixing / structural mismatches

	Must never:
	- Post JEs.
	- Write to DB.
	"""
	if not invoice_doc:
		return
	gt = flt(getattr(invoice_doc, "grand_total", None) or 0)
	total = flt(plan.total_requested)
	if total > gt + 1e-9:
		frappe.throw(
			_("Total PDC advance application exceeds invoice total."),
			title=_("PDC Advance"),
		)

	# Per-instrument check: sum of all rows for a PDC <= instrument open
	by_pdc: dict[str, float] = {}
	for d in plan.by_resource or ():
		if d.key.type != "instrument":
			continue
		by_pdc[d.key.post_dated_cheque] = by_pdc.get(d.key.post_dated_cheque, 0.0) + flt(d.requested_amount)

	for pdc, req in by_pdc.items():
		okey = ResourceKey(type="instrument", post_dated_cheque=pdc)
		open_amt = flt((opens or {}).get(okey))
		if req > open_amt + 1e-9:
			frappe.throw(
				_("Applied amount exceeds open advance on PDC {0}.").format(pdc),
				title=_("PDC Advance"),
			)

	# Per-bucket check: order_based only
	for d in plan.by_resource or ():
		if d.key.type != "order_bucket":
			continue
		open_amt = flt((opens or {}).get(d.key))
		if flt(d.requested_amount) > open_amt + 1e-9:
			frappe.throw(
				_("Applied amount exceeds open advance on PDC {0} for {1} {2}.").format(
					d.key.post_dated_cheque, d.key.order_doctype, d.key.order_name
				),
				title=_("PDC Advance"),
			)


def validate_before_invoice_submit(invoice_doc) -> None:
	"""Entry point for PI/SI `before_submit` (validation only, no writes, no locks).

	Enforces:
	- strict normalization of draft rows (explicit scope required)
	- scope rules and PDC eligibility rules (recognized/alive/submitted/matching)
	- financial checks using current open helpers:
	  - invoice total ceiling
	  - per-instrument open
	  - per-order-bucket open for order_based

	Must never:
	- Post JEs
	- Mutate DB
	- Acquire locks
	"""
	rows = normalize_invoice_pdc_application_rows(invoice_doc)
	if not rows:
		return
	plan = build_consumption_plan(invoice_doc, rows)
	opens = recompute_canonical_opens(plan)
	validate_consumption_plan(invoice_doc, plan, opens)

	# Mixed-pool guardrail warning (non-blocking).
	dt = (getattr(invoice_doc, "doctype", None) or "").strip()
	order_field = "purchase_order" if dt == "Purchase Invoice" else "sales_order"
	order_dt = "Purchase Order" if dt == "Purchase Invoice" else "Sales Order"
	order_nm = ""
	for it in getattr(invoice_doc, "items", None) or []:
		v = (getattr(it, order_field, None) or "").strip()
		if v:
			order_nm = v
			break
	if order_nm:
		order_open = flt(get_open_advance_for_order(order_dt, order_nm).get("open_amount"))
		order_req = flt(sum(flt(r.amount_in_pdc_currency) for r in rows if r.advance_scope == "order_based"))
		gen_req = flt(sum(flt(r.amount_in_pdc_currency) for r in rows if r.advance_scope == "general"))
		if gen_req > 1e-9 and order_open > order_req + 1e-9:
			frappe.msgprint(
				_(
					"General PDC Advance is being used while order-based advance is still available for this order."
				),
				title=_("PDC Advance"),
				indicator="orange",
			)


def apply_pdc_advance_on_submit(invoice_doc) -> str | None:
	"""Apply Advance PDC on invoice submit (atomic).

	Side effects (when implemented):
	- Lock resources, recompute opens, validate, post application JE,
	  persist application rows with status=posted and posted_je link.

	Transactional requirement:
	- JE submit and row persistence must be in the same DB transaction.

	Returns:
	- Posted JE name (or None if no application rows).
	"""
	raise NotImplementedError


def reverse_pdc_advance_on_cancel(invoice_doc) -> str | None:
	"""Reverse Advance PDC application on invoice cancel (atomic).

	Side effects (when implemented):
	- Lock resources, post reversal JE, persist application rows with status=reversed and reversal_je link.

	Returns:
	- Reversal JE name (or None if nothing to reverse).
	"""
	raise NotImplementedError


__all__ = [
	"get_advance_candidates_for_invoice_api",
	"get_advance_candidates_for_invoice",
	"validate_pdc_invoice_application_rows_structural",
	"validate_before_invoice_submit",
	"normalize_invoice_pdc_application_rows",
	"build_consumption_plan",
	"lock_consumption_resources",
	"recompute_canonical_opens",
	"validate_consumption_plan",
	"apply_pdc_advance_on_submit",
	"reverse_pdc_advance_on_cancel",
]
