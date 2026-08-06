# Copyright (c) 2026, ERPNext Extensions contributors
"""Provenance-based IRR residual classification and shared ResidualDecision evaluator.

Contract (3.8.6)
----------------
Class A: residual reproduced exactly by approved iran_accounting rounding helpers
         for the voucher flow (provenance-first; path-derived bound only after).
Class B: valuation inconsistency / invalid rate / unexplained gap — fail closed.
Net Class A == 0 → full Round Off subsystem bypass (no Account/CC/dim/partner).
Net Class A != 0 → Company Round Off Account/CC + Company Round Off Dimension
Defaults + safe non-stock partner (never Stock Adjustment fallback).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import frappe
from frappe import _
from frappe.utils import flt

from erpnext_extensions.iran_accounting.domain.currency import (
	amount_rate_qty_residual,
	get_company_currency,
	integer_valuation_rate_from_amount,
	is_irr_company,
	round_currency,
	round_monetary_rate,
	round_row_amount,
)

STATUS_BYPASS = "bypass"
STATUS_READY = "ready"
STATUS_CLASS_B = "class_b_error"
STATUS_CONFIG = "config_error"
STATUS_PARTNER = "partner_error"


@dataclass
class ResidualDecision:
	status: str = STATUS_BYPASS
	class_a_rows: list[dict[str, Any]] = field(default_factory=list)
	class_b_rows: list[dict[str, Any]] = field(default_factory=list)
	net_signed_debit: float = 0.0
	round_off_account: str | None = None
	round_off_cost_center: str | None = None
	dimensions: dict[str, Any] = field(default_factory=dict)
	partner: Any | None = None
	partner_checked: bool = False
	messages: list[str] = field(default_factory=list)
	diagnostics: list[dict[str, Any]] = field(default_factory=list)

	@property
	def is_bypass(self) -> bool:
		return self.status == STATUS_BYPASS

	@property
	def is_ready(self) -> bool:
		return self.status == STATUS_READY

	@property
	def is_error(self) -> bool:
		return self.status in (STATUS_CLASS_B, STATUS_CONFIG, STATUS_PARTNER)


def _dimension_fieldnames() -> list[str]:
	from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import (
		get_accounting_dimensions,
	)

	return [d for d in get_accounting_dimensions() if d != "cost_center"]


def _row_dimension_values(row) -> dict[str, Any]:
	out = {}
	for fieldname in _dimension_fieldnames():
		val = row.get(fieldname) if hasattr(row, "get") else getattr(row, fieldname, None)
		if val not in (None, ""):
			out[fieldname] = val
	return out


def _path_derived_bound(qty) -> float:
	"""Secondary bound after provenance: integer amount÷qty remainder is < |qty|."""
	q = abs(flt(qty))
	return max(1.0, q) if q else 1.0


def classify_amount_rate_residual(
	*,
	qty,
	authoritative_amount,
	valuation_rate,
	currency: str,
	item_code: str | None = None,
	idx: int | None = None,
	row_name: str | None = None,
	extra: dict | None = None,
) -> dict[str, Any]:
	"""Classify one amount vs rate-first product residual using approved helpers only."""
	qty = flt(qty)
	auth = flt(authoritative_amount)
	rate = valuation_rate
	diag = {
		"item_code": item_code,
		"idx": idx,
		"row_name": row_name,
		"qty": qty,
		"authoritative_amount": auth,
		"valuation_rate": rate,
		**(extra or {}),
	}

	if not qty:
		return {
			**diag,
			"class": "skip",
			"reason": "zero_qty",
			"residual": 0,
			"round_off_debit": 0,
		}

	if rate in (None, ""):
		if not auth:
			return {**diag, "class": "skip", "reason": "missing_rate_zero_amount", "residual": 0}
		return {
			**diag,
			"class": "B",
			"reason": "missing_valuation_rate",
			"residual": auth,
			"expected_valuation_rate": integer_valuation_rate_from_amount(auth, qty, currency)
			if auth
			else None,
			"expected_amount": None,
		}

	rate_f = flt(rate)
	if rate_f <= 0 and auth:
		return {
			**diag,
			"class": "B",
			"reason": "valuation_rate_le_zero_with_nonzero_amount",
			"residual": auth,
			"expected_valuation_rate": integer_valuation_rate_from_amount(auth, qty, currency),
			"expected_amount": round_row_amount(qty, integer_valuation_rate_from_amount(auth, qty, currency), currency),
		}

	rounded_rate = flt(round_monetary_rate(rate_f, currency))
	if rounded_rate != rate_f:
		return {
			**diag,
			"class": "B",
			"reason": "non_integer_rate_under_irr_contract",
			"residual": amount_rate_qty_residual(auth, qty, rate_f, currency),
			"expected_valuation_rate": rounded_rate,
			"expected_amount": round_row_amount(qty, rounded_rate, currency),
		}

	derived = flt(round_row_amount(qty, rate_f, currency))
	residual = flt(amount_rate_qty_residual(auth, qty, rate_f, currency))
	rate_from_amount = flt(integer_valuation_rate_from_amount(auth, qty, currency)) if auth else None

	diag.update(
		{
			"rate_derived_amount": derived,
			"residual": residual,
			"expected_valuation_rate": rate_from_amount,
			"expected_amount": derived,
		}
	)

	if not residual:
		return {**diag, "class": "skip", "reason": "zero_residual"}

	# Provenance: amount-authoritative integer VR pipeline (SE compose / SR amount auth)
	if rate_from_amount is not None and rate_f == rate_from_amount:
		bound = _path_derived_bound(qty)
		if abs(residual) >= bound:
			return {
				**diag,
				"class": "B",
				"reason": "provenance_matched_but_exceeds_path_derived_bound",
				"path_derived_bound": bound,
			}
		return {
			**diag,
			"class": "A",
			"reason": "amount_authoritative_integer_valuation_rate",
			"path_derived_bound": bound,
		}

	# Provenance: rate-first product should equal amount → residual must be 0; else mismatch
	if auth == derived:
		return {**diag, "class": "skip", "reason": "auth_equals_rate_first_product"}

	return {
		**diag,
		"class": "B",
		"reason": "amount_rate_mismatch_not_reproducible_by_approved_pipeline",
	}


def enrich_candidate_dimensions(candidate: dict, row) -> dict:
	candidate["dimensions"] = _row_dimension_values(row)
	return candidate


def classify_document_residuals(doc) -> tuple[list[dict], list[dict]]:
	"""Collect and classify residual candidates for supported doctypes."""
	from erpnext_extensions.iran_accounting.domain.irr_rounding_residual import (
		_transfer_qty,
		collect_document_residuals,
		round_off_signed_debit,
		stock_entry_excludes_irr_residual_round_off,
	)

	if stock_entry_excludes_irr_residual_round_off(doc):
		return [], []

	ccy = get_company_currency(doc.company)
	class_a: list[dict] = []
	class_b: list[dict] = []

	if doc.doctype == "Purchase Receipt":
		for row in doc.get("items") or []:
			qty = flt(row.get("qty"))
			auth = flt(
				row.get("base_amount")
				if row.get("base_amount") not in (None, "")
				else row.get("amount")
			)
			rate = row.get("valuation_rate")
			if rate in (None, "") and row.get("base_rate") not in (None, ""):
				rate = row.get("base_rate")
			classified = classify_amount_rate_residual(
				qty=qty,
				authoritative_amount=auth,
				valuation_rate=rate,
				currency=ccy,
				item_code=row.get("item_code"),
				idx=row.get("idx"),
				row_name=row.get("name"),
				extra={
					"base_rate": row.get("base_rate"),
					"base_amount": row.get("base_amount"),
					"amount": row.get("amount"),
					"landed_cost_voucher_amount": row.get("landed_cost_voucher_amount"),
				},
			)
			enrich_candidate_dimensions(classified, row)
			_bucket(classified, class_a, class_b, incoming=True, currency=ccy)

	elif doc.doctype == "Stock Entry":
		for row in doc.get("items") or []:
			if row.get("s_warehouse") and row.get("t_warehouse"):
				continue
			qty = _transfer_qty(row)
			auth = flt(row.get("amount"))
			rate = row.get("valuation_rate")
			classified = classify_amount_rate_residual(
				qty=qty,
				authoritative_amount=auth,
				valuation_rate=rate,
				currency=ccy,
				item_code=row.get("item_code"),
				idx=row.get("idx"),
				row_name=row.get("name"),
				extra={
					"basic_rate": row.get("basic_rate"),
					"basic_amount": row.get("basic_amount"),
					"additional_cost": row.get("additional_cost"),
					"landed_cost_voucher_amount": row.get("landed_cost_voucher_amount"),
				},
			)
			enrich_candidate_dimensions(classified, row)
			incoming = bool(row.get("t_warehouse")) and not row.get("s_warehouse")
			_bucket(classified, class_a, class_b, incoming=incoming, currency=ccy)

	elif doc.doctype == "Stock Reconciliation":
		# Keep SR movement residual collection, then classify each resulting residual.
		for r in collect_document_residuals(doc):
			row = _find_row(doc, r.get("row_name"))
			classified = classify_amount_rate_residual(
				qty=r.get("qty"),
				authoritative_amount=flt(r.get("rate_derived_amount")) + flt(r.get("residual")),
				valuation_rate=r.get("valuation_rate"),
				currency=ccy,
				item_code=r.get("item_code"),
				idx=r.get("idx"),
				row_name=r.get("row_name"),
			)
			# Prefer explicit residual from SR collector when provenance matches amount path
			if classified.get("class") == "A":
				classified["residual"] = r.get("residual")
			if row:
				enrich_candidate_dimensions(classified, row)
			else:
				classified["dimensions"] = {}
			_bucket(
				classified,
				class_a,
				class_b,
				incoming=bool(r.get("incoming")),
				currency=ccy,
				preset_debit=r.get("round_off_debit"),
			)

	return class_a, class_b


def _find_row(doc, row_name):
	if not row_name:
		return None
	for row in doc.get("items") or []:
		if row.get("name") == row_name:
			return row
	return None


def _bucket(
	classified: dict,
	class_a: list,
	class_b: list,
	*,
	incoming: bool,
	currency: str,
	preset_debit=None,
):
	from erpnext_extensions.iran_accounting.domain.irr_rounding_residual import round_off_signed_debit

	cls = classified.get("class")
	if cls == "skip":
		return
	residual = flt(classified.get("residual"))
	classified["incoming"] = incoming
	classified["round_off_debit"] = (
		flt(preset_debit)
		if preset_debit is not None and cls == "A"
		else round_off_signed_debit(residual, incoming=incoming)
	)
	classified["round_off_debit"] = round_currency(classified["round_off_debit"], currency)
	if cls == "A":
		class_a.append(classified)
	elif cls == "B":
		class_b.append(classified)


def _format_class_b_message(doc, rows: list[dict]) -> str:
	parts = [
		_(
			"IRR rate-rounding residual rejected: valuation inconsistency (Class B). "
			"Round Off Account and Stock Adjustment Account must not absorb this gap."
		)
	]
	parts.append(_("Voucher: {0} {1}").format(doc.doctype, doc.name or _("new")))
	for r in rows[:8]:
		parts.append(
			_(
				"Row {idx} item {item}: qty={qty}, valuation_rate={rate}, "
				"amount={auth}, expected_rate={exp_rate}, expected_amount={exp_amt}, "
				"residual={residual}, reason={reason}"
			).format(
				idx=r.get("idx"),
				item=r.get("item_code"),
				qty=r.get("qty"),
				rate=r.get("valuation_rate"),
				auth=r.get("authoritative_amount"),
				exp_rate=r.get("expected_valuation_rate"),
				exp_amt=r.get("expected_amount"),
				residual=r.get("residual"),
				reason=r.get("reason"),
			)
		)
	return "\n".join(parts)


def get_company_round_off_dimension_defaults(company: str) -> dict[str, str]:
	"""Map fieldname → default_value from Company child table (no AD defaults)."""
	if not frappe.db.exists("DocType", "Round Off Dimension Default"):
		return {}
	rows = frappe.get_all(
		"Round Off Dimension Default",
		filters={"parent": company, "parenttype": "Company"},
		fields=["accounting_dimension", "default_value"],
		order_by="idx asc",
	)
	out: dict[str, str] = {}
	for row in rows:
		fn = (row.accounting_dimension or "").strip()
		if not fn or fn in ("cost_center", "account"):
			continue
		if row.default_value:
			out[fn] = row.default_value
	return out


def resolve_round_off_dimensions(
	*,
	doc,
	company: str,
	round_off_account: str,
	class_a_rows: list[dict],
) -> dict[str, Any]:
	"""Header → unique Class A row value → Company Round Off Dimension Defaults → fail."""
	from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import (
		get_checks_for_pl_and_bs_accounts,
	)

	report_type = frappe.get_cached_value("Account", round_off_account, "report_type")
	meta = frappe.get_meta(doc.doctype)
	company_defaults = get_company_round_off_dimension_defaults(company)
	resolved: dict[str, Any] = {}

	# Optional: copy project from header when present (non-mandatory convenience)
	if meta.has_field("project") and doc.get("project"):
		resolved["project"] = doc.get("project")

	for dimension in get_checks_for_pl_and_bs_accounts():
		if dimension.company != company:
			continue
		fieldname = dimension.fieldname
		if fieldname in ("cost_center", "account"):
			continue
		mandatory = (report_type == "Profit and Loss" and dimension.mandatory_for_pl) or (
			report_type == "Balance Sheet" and dimension.mandatory_for_bs
		)
		if not mandatory:
			continue

		# 1) Header per field (do not require all dimensions on meta)
		if meta.has_field(fieldname) and doc.get(fieldname):
			resolved[fieldname] = doc.get(fieldname)
			continue

		# 2) Unique non-empty among Class A residual source rows
		values = {
			r.get("dimensions", {}).get(fieldname)
			for r in class_a_rows
			if r.get("dimensions", {}).get(fieldname) not in (None, "")
		}
		if len(values) == 1:
			resolved[fieldname] = next(iter(values))
			continue

		# 3) Company Round Off Dimension Defaults (never AD default_dimension)
		if company_defaults.get(fieldname):
			resolved[fieldname] = company_defaults[fieldname]
			continue

		# 4) Fail
		frappe.throw(
			_(
				"Mandatory accounting dimension {0} is missing for IRR Round Off residual on "
				"Company {1}. Set it on the voucher, ensure a single value on residual rows, "
				"or configure Company → Round Off Dimension Defaults."
			).format(frappe.bold(dimension.label or fieldname), frappe.bold(company)),
			title=_("Missing Round Off Dimension"),
		)

	return resolved


def evaluate_irr_rate_rounding_residual(
	doc,
	gl_entries=None,
	context=None,
) -> ResidualDecision:
	"""Shared validate/apply/RIV decision for IRR rate-rounding residual only."""
	from erpnext_extensions.iran_accounting.domain.irr_rounding_residual import (
		SUPPORTED_RESIDUAL_DOCTYPES,
		_pick_adjustable_non_stock_leg,
		_protected_reclass_accounts,
		resolve_company_round_off,
		stock_entry_excludes_irr_residual_round_off,
		validate_round_off_configuration,
	)

	_ = context
	decision = ResidualDecision()

	if not getattr(doc, "company", None) or not is_irr_company(doc.company):
		decision.status = STATUS_BYPASS
		decision.messages.append("non_irr_or_missing_company")
		return decision

	if doc.doctype not in SUPPORTED_RESIDUAL_DOCTYPES:
		decision.status = STATUS_BYPASS
		decision.messages.append("unsupported_doctype")
		return decision

	if stock_entry_excludes_irr_residual_round_off(doc):
		decision.status = STATUS_BYPASS
		decision.messages.append("manufacture_repack_excluded_use_stock_adjustment")
		return decision

	if doc.doctype == "Stock Entry":
		from erpnext_extensions.iran_accounting.zero_value_transfer import (
			_should_force_balanced_transfer_gl,
		)

		precision = 0
		if hasattr(doc, "get_debit_field_precision"):
			precision = doc.get_debit_field_precision()
		if _should_force_balanced_transfer_gl(doc, precision):
			decision.status = STATUS_BYPASS
			decision.messages.append("zero_value_transfer_gl_path")
			return decision

	class_a, class_b = classify_document_residuals(doc)
	decision.class_a_rows = class_a
	decision.class_b_rows = class_b
	decision.diagnostics = list(class_b) + list(class_a)

	if class_b:
		decision.status = STATUS_CLASS_B
		decision.messages.append(_format_class_b_message(doc, class_b))
		return decision

	ccy = get_company_currency(doc.company)
	net = round_currency(sum(flt(r.get("round_off_debit")) for r in class_a), ccy)
	decision.net_signed_debit = flt(net)

	if not decision.net_signed_debit:
		decision.status = STATUS_BYPASS
		decision.messages.append("net_class_a_zero")
		return decision

	# Net Class A != 0 → resolve Round Off masters (not before)
	try:
		cfg = resolve_company_round_off(doc.company, require=True)
		validate_round_off_configuration(doc.company, cfg["account"], cfg["cost_center"])
	except Exception as e:
		decision.status = STATUS_CONFIG
		decision.messages.append(str(e))
		return decision

	decision.round_off_account = cfg["account"]
	decision.round_off_cost_center = cfg["cost_center"]

	try:
		decision.dimensions = resolve_round_off_dimensions(
			doc=doc,
			company=doc.company,
			round_off_account=cfg["account"],
			class_a_rows=class_a,
		)
	except Exception as e:
		decision.status = STATUS_CONFIG
		decision.messages.append(str(e))
		return decision

	if gl_entries is None:
		# Preflight without GL: config+dims OK; partner checked at apply.
		decision.status = STATUS_READY
		decision.partner_checked = False
		decision.messages.append("ready_pending_partner_at_apply")
		return decision

	protected = _protected_reclass_accounts(doc)
	partner = _pick_adjustable_non_stock_leg(
		gl_entries,
		doc.company,
		cfg["account"],
		protected_accounts=protected,
		reclass_magnitude=decision.net_signed_debit,
	)
	decision.partner_checked = True
	if not partner:
		examined = []
		for entry in gl_entries:
			acc = entry.get("account")
			examined.append(
				{
					"account": acc,
					"debit": entry.get("debit"),
					"credit": entry.get("credit"),
				}
			)
		decision.status = STATUS_PARTNER
		examined_txt = ", ".join(
			f"{e['account']}(D={e['debit']}/C={e['credit']})" for e in examined[:20]
		)
		protected_txt = ", ".join(sorted(protected)) if protected else "none"
		decision.messages.append(
			"No safe non-stock GL partner is available to reclassify the IRR Round Off residual.\n"
			f"Voucher: {doc.doctype} {doc.name or 'new'}\n"
			f"Net residual (signed debit): {decision.net_signed_debit}\n"
			f"Round Off Account: {cfg['account']}\n"
			"Stock Adjustment Account must not be used as a fallback.\n"
			f"Protected Additional Cost accounts: {protected_txt}\n"
			f"GL accounts examined: {examined_txt}"
		)
		return decision

	decision.partner = partner
	decision.status = STATUS_READY
	decision.messages.append("ready")
	return decision


def raise_residual_decision(decision: ResidualDecision) -> None:
	"""Throw for non-ready error statuses."""
	if not decision.is_error:
		return
	title = {
		STATUS_CLASS_B: _("IRR Residual Classification"),
		STATUS_CONFIG: _("IRR Round Off Configuration"),
		STATUS_PARTNER: _("IRR Round Off Partner"),
	}.get(decision.status, _("IRR Round Off"))
	msg = "\n".join(decision.messages) or decision.status
	frappe.throw(msg, title=title)
