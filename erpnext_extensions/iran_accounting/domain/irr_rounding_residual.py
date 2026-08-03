# Copyright (c) 2026, ERPNext Extensions contributors
"""IRR integer-rate rounding residual → Company Round Off Account.

Contract
--------
rate_derived_amount = ROUND_HALF_UP(qty × integer_valuation_rate, 0)
authoritative_amount = finalized row / SLE movement amount
rounding_residual = authoritative_amount − rate_derived_amount

Inventory GL and SLE keep authoritative_amount.
When residual ≠ 0, post an explicit Round Off GL leg (Company.round_off_account /
round_off_cost_center) and reclassify the same magnitude from a non-Stock GL leg
so the voucher stays balanced without changing inventory value.

Debit/credit (Round Off signed debit; positive = Debit Round Off):
  incoming inventory movement: round_off_debit = −residual
  outgoing inventory movement: round_off_debit = +residual

Example (incoming, amount=1371, qty=7, rate=196):
  residual = 1371 − 1372 = −1
  round_off_debit = −(−1) = +1  → Debit Round Off 1
"""

from __future__ import annotations

from typing import Any

import frappe
from frappe import _
from frappe.utils import cint, flt

from erpnext_extensions.iran_accounting.domain.currency import (
	amount_rate_qty_residual,
	get_company_currency,
	is_irr_company,
	round_currency,
	round_row_amount,
)

IRR_RATE_ROUNDING_RESIDUAL_REMARK = "IRR rate rounding residual"
# Explicit in-memory GL-map marker (not a DocType field). Durable twin after persist is
# Company.round_off_account + IRR_RATE_ROUNDING_RESIDUAL_REMARK in remarks.
IRR_RATE_ROUNDING_RESIDUAL_MARKER = "_irr_rate_rounding_residual"

SUPPORTED_RESIDUAL_DOCTYPES = (
	"Stock Entry",
	"Purchase Receipt",
	"Stock Reconciliation",
)

# Manufacture / Repack: incoming≠outgoing from integer-rate policy is a stock valuation
# difference → Company Stock Adjustment (vanilla ERPNext). Round Off must NOT compensate
# IRR rate residuals on these purposes.
IRR_RESIDUAL_ROUND_OFF_EXCLUDED_STOCK_ENTRY_PURPOSES = frozenset(
	{
		"Manufacture",
		"Repack",
	}
)


def stock_entry_excludes_irr_residual_round_off(doc) -> bool:
	"""True when IRR residual Round Off must not touch this Stock Entry."""
	if getattr(doc, "doctype", None) != "Stock Entry":
		return False
	return (doc.get("purpose") or "") in IRR_RESIDUAL_ROUND_OFF_EXCLUDED_STOCK_ENTRY_PURPOSES


def is_irr_rate_rounding_residual_gl(
	entry,
	*,
	company: str | None = None,
	round_off_account: str | None = None,
) -> bool:
	"""Structural detection of IRR residual Round Off GL rows.

	Prefer the explicit in-memory marker. After persist (marker stripped by make_entry),
	require both Company.round_off_account and the residual remark — never remarks alone.
	"""
	if not entry:
		return False
	if entry.get(IRR_RATE_ROUNDING_RESIDUAL_MARKER):
		return True

	account = entry.get("account")
	if not account:
		return False
	if round_off_account is None and company:
		try:
			round_off_account = frappe.get_cached_value("Company", company, "round_off_account")
		except Exception:
			round_off_account = None
	if not round_off_account or account != round_off_account:
		return False
	return IRR_RATE_ROUNDING_RESIDUAL_REMARK in (entry.get("remarks") or "")


def assert_irr_residual_round_off_masters(entry, company: str) -> None:
	"""Fail closed: residual Round Off must use Company Round Off Account + Cost Center only."""
	cfg = resolve_company_round_off(company, require=True)
	if entry.get("account") != cfg["account"]:
		frappe.throw(
			_("IRR Round Off GL account {0} must equal Company.round_off_account {1}.").format(
				frappe.bold(entry.get("account")), frappe.bold(cfg["account"])
			),
			title=_("IRR Round Off Account"),
		)
	if entry.get("cost_center") != cfg["cost_center"]:
		frappe.throw(
			_("IRR Round Off GL cost center {0} must equal Company.round_off_cost_center {1}.").format(
				frappe.bold(entry.get("cost_center")), frappe.bold(cfg["cost_center"])
			),
			title=_("IRR Round Off Cost Center"),
		)


def stamp_irr_residual_round_off_masters(entry, company: str) -> None:
	"""Set account/cost_center solely from Company Round Off masters + residual marker."""
	cfg = resolve_company_round_off(company, require=True)
	entry["account"] = cfg["account"]
	entry["cost_center"] = cfg["cost_center"]
	entry[IRR_RATE_ROUNDING_RESIDUAL_MARKER] = 1
	assert_irr_residual_round_off_masters(entry, company)


def rate_derived_amount(qty, valuation_rate, currency: str | None):
	"""ROUND_HALF_UP(qty × ROUND_HALF_UP(valuation_rate))."""
	return round_row_amount(qty, valuation_rate, currency)


def compute_rounding_residual(authoritative_amount, qty, valuation_rate, currency: str | None):
	"""authoritative_amount − rate_derived_amount (IRR integer)."""
	return amount_rate_qty_residual(authoritative_amount, qty, valuation_rate, currency)


def round_off_signed_debit(residual, *, incoming: bool) -> float:
	"""Positive → Debit Round Off; negative → Credit Round Off."""
	return flt(-residual if incoming else residual)


def resolve_company_round_off(company: str, *, require: bool = True) -> dict[str, str | None]:
	"""Resolve Company.round_off_account / round_off_cost_center (no hard-coded names)."""
	account, cost_center = frappe.get_cached_value(
		"Company", company, ["round_off_account", "round_off_cost_center"]
	) or (None, None)
	if require:
		validate_round_off_configuration(company, account, cost_center)
	return {"account": account, "cost_center": cost_center}


def validate_round_off_configuration(company: str, account: str | None = None, cost_center: str | None = None) -> None:
	"""Fail closed when residual posting requires Round Off masters."""
	if account is None and cost_center is None:
		account, cost_center = frappe.get_cached_value(
			"Company", company, ["round_off_account", "round_off_cost_center"]
		) or (None, None)

	if not account:
		frappe.throw(
			_("Please set Round Off Account on Company {0} for IRR rate rounding residuals.").format(
				frappe.bold(company)
			),
			title=_("Missing Round Off Account"),
		)
	if not cost_center:
		frappe.throw(
			_("Please set Round Off Cost Center on Company {0} for IRR rate rounding residuals.").format(
				frappe.bold(company)
			),
			title=_("Missing Round Off Cost Center"),
		)

	acc = frappe.db.get_value(
		"Account",
		account,
		["name", "company", "is_group", "disabled", "account_type"],
		as_dict=True,
	)
	if not acc:
		frappe.throw(_("Round Off Account {0} does not exist.").format(frappe.bold(account)))
	if acc.company != company:
		frappe.throw(
			_("Round Off Account {0} does not belong to Company {1}.").format(
				frappe.bold(account), frappe.bold(company)
			)
		)
	if cint(acc.is_group):
		frappe.throw(_("Round Off Account {0} must not be a group.").format(frappe.bold(account)))
	if cint(acc.disabled):
		frappe.throw(_("Round Off Account {0} is disabled.").format(frappe.bold(account)))

	cc = frappe.db.get_value(
		"Cost Center",
		cost_center,
		["name", "company", "disabled", "is_group"],
		as_dict=True,
	)
	if not cc:
		frappe.throw(_("Round Off Cost Center {0} does not exist.").format(frappe.bold(cost_center)))
	if cc.company != company:
		frappe.throw(
			_("Round Off Cost Center {0} does not belong to Company {1}.").format(
				frappe.bold(cost_center), frappe.bold(company)
			)
		)
	if cint(cc.disabled):
		frappe.throw(_("Round Off Cost Center {0} is disabled.").format(frappe.bold(cost_center)))


def _transfer_qty(row) -> float:
	return flt(row.get("transfer_qty") if row.get("transfer_qty") not in (None, "") else row.get("qty"))


def collect_stock_entry_residuals(doc) -> list[dict[str, Any]]:
	"""Per-row residuals; skip dual-warehouse transfer rows (in/out cancel).

	Manufacture / Repack are excluded: valuation gaps use Stock Adjustment, not Round Off.
	"""
	if stock_entry_excludes_irr_residual_round_off(doc):
		return []
	ccy = get_company_currency(doc.company)
	out: list[dict[str, Any]] = []
	for row in doc.get("items") or []:
		if row.get("s_warehouse") and row.get("t_warehouse"):
			continue
		qty = _transfer_qty(row)
		auth = flt(row.get("amount"))
		rate = row.get("valuation_rate")
		if rate in (None, "") or not qty:
			continue
		residual = compute_rounding_residual(auth, qty, rate, ccy)
		if not residual:
			continue
		incoming = bool(row.get("t_warehouse")) and not row.get("s_warehouse")
		out.append(
			{
				"row_name": row.get("name"),
				"idx": row.get("idx"),
				"item_code": row.get("item_code"),
				"qty": qty,
				"valuation_rate": rate,
				"authoritative_amount": auth,
				"rate_derived_amount": rate_derived_amount(qty, rate, ccy),
				"residual": residual,
				"incoming": incoming,
				"round_off_debit": round_off_signed_debit(residual, incoming=incoming),
				"cost_center": row.get("cost_center"),
			}
		)
	return out


def collect_purchase_receipt_residuals(doc) -> list[dict[str, Any]]:
	ccy = get_company_currency(doc.company)
	out: list[dict[str, Any]] = []
	for row in doc.get("items") or []:
		qty = flt(row.get("qty"))
		auth = flt(row.get("base_amount") if row.get("base_amount") not in (None, "") else row.get("amount"))
		rate = row.get("valuation_rate")
		if rate in (None, "") and row.get("base_rate") not in (None, ""):
			rate = row.get("base_rate")
		if rate in (None, "") or not qty:
			continue
		residual = compute_rounding_residual(auth, qty, rate, ccy)
		if not residual:
			continue
		out.append(
			{
				"row_name": row.get("name"),
				"idx": row.get("idx"),
				"item_code": row.get("item_code"),
				"qty": qty,
				"valuation_rate": rate,
				"authoritative_amount": auth,
				"rate_derived_amount": rate_derived_amount(qty, rate, ccy),
				"residual": residual,
				"incoming": True,
				"round_off_debit": round_off_signed_debit(residual, incoming=True),
				"cost_center": row.get("cost_center"),
			}
		)
	return out


def collect_stock_reconciliation_residuals(doc) -> list[dict[str, Any]]:
	ccy = get_company_currency(doc.company)
	out: list[dict[str, Any]] = []
	for row in doc.get("items") or []:
		qty = flt(row.get("qty"))
		cur_qty = flt(row.get("current_qty"))
		auth_diff = flt(row.get("amount_difference"))
		new_res = compute_rounding_residual(row.get("amount"), qty, row.get("valuation_rate"), ccy) if qty else 0
		cur_res = (
			compute_rounding_residual(
				row.get("current_amount"), cur_qty, row.get("current_valuation_rate"), ccy
			)
			if cur_qty
			else 0
		)
		# Movement residual = new residual − current residual
		residual = round_currency(flt(new_res) - flt(cur_res), ccy)
		if not residual:
			continue
		incoming = auth_diff >= 0
		out.append(
			{
				"row_name": row.get("name"),
				"idx": row.get("idx"),
				"item_code": row.get("item_code"),
				"qty": qty,
				"valuation_rate": row.get("valuation_rate"),
				"authoritative_amount": auth_diff,
				"rate_derived_amount": round_currency(auth_diff - residual, ccy),
				"residual": residual,
				"incoming": incoming,
				"round_off_debit": round_off_signed_debit(residual, incoming=incoming),
				"cost_center": row.get("cost_center"),
			}
		)
	return out


def collect_document_residuals(doc) -> list[dict[str, Any]]:
	if doc.doctype == "Stock Entry":
		return collect_stock_entry_residuals(doc)
	if doc.doctype == "Purchase Receipt":
		return collect_purchase_receipt_residuals(doc)
	if doc.doctype == "Stock Reconciliation":
		return collect_stock_reconciliation_residuals(doc)
	return []


def document_has_rounding_residual(doc) -> bool:
	return any(flt(r.get("residual")) for r in collect_document_residuals(doc))


def assert_round_off_ready_if_needed(doc) -> None:
	"""Before submit: residual ≠ 0 requires valid Company Round Off config."""
	if not is_irr_company(doc.company):
		return
	if doc.doctype not in SUPPORTED_RESIDUAL_DOCTYPES:
		return
	if stock_entry_excludes_irr_residual_round_off(doc):
		return
	if not document_has_rounding_residual(doc):
		return
	resolve_company_round_off(doc.company, require=True)


def strip_irr_rate_rounding_residual_gl(gl_map: list) -> list:
	"""Remove prior IRR residual Round Off rows (idempotent rebuild)."""
	if not gl_map:
		return gl_map
	company = None
	if gl_map:
		company = gl_map[0].get("company")
	kept = [
		entry
		for entry in gl_map
		if not is_irr_rate_rounding_residual_gl(entry, company=company)
	]
	gl_map[:] = kept
	return gl_map


def _is_stock_account(account: str | None) -> bool:
	if not account:
		return False
	return frappe.get_cached_value("Account", account, "account_type") == "Stock"


def _is_stock_adjustment_account(account: str | None, company: str | None = None) -> bool:
	"""Stock Adjustment holds inventory valuation differences — never reclassify into Round Off."""
	if not account:
		return False
	try:
		account_type = frappe.get_cached_value("Account", account, "account_type")
	except Exception:
		account_type = None
	if account_type == "Stock Adjustment":
		return True
	if company:
		try:
			company_adj = frappe.get_cached_value("Company", company, "stock_adjustment_account")
		except Exception:
			company_adj = None
		if company_adj and account == company_adj:
			return True
	return False


def _pick_adjustable_non_stock_leg(
	gl_map: list,
	company: str,
	round_off_account: str,
	*,
	protected_accounts: set[str] | None = None,
	reclass_magnitude: float = 0,
):
	"""Largest non-Stock, non-Round-Off, non-Stock-Adjustment monetary leg.

	Protected accounts (e.g. Additional Cost expense) may be used only when their
	magnitude strictly exceeds the reclass amount so the Add Cost GL remains visible.
	"""
	protected = protected_accounts or set()
	need = abs(flt(reclass_magnitude))
	candidates = []
	for entry in gl_map:
		account = entry.get("account")
		if not account or account == round_off_account:
			continue
		if _is_stock_account(account):
			continue
		if _is_stock_adjustment_account(account, company):
			continue
		mag = max(flt(entry.get("debit")), flt(entry.get("credit")))
		if not mag:
			continue
		if account in protected and mag <= need:
			continue
		candidates.append((mag, entry))
	if not candidates:
		return None
	candidates.sort(key=lambda x: x[0], reverse=True)
	return candidates[0][1]


def _protected_reclass_accounts(doc) -> set[str]:
	"""Accounts that must remain visible on the voucher GL (not Round Off fodder)."""
	protected: set[str] = set()
	if getattr(doc, "doctype", None) == "Stock Entry":
		for row in doc.get("additional_costs") or []:
			if row.get("expense_account"):
				protected.add(row.get("expense_account"))
	return protected


def _apply_signed_debit_to_entry(entry, signed_debit: float, precision: int, currency: str) -> None:
	"""Add signed_debit to entry (positive increases debit / decreases credit)."""
	signed_debit = round_currency(signed_debit, currency)
	if not signed_debit:
		return
	if signed_debit > 0:
		if flt(entry.get("credit")):
			# reduce credit first
			credit = flt(entry.get("credit"))
			if credit >= signed_debit:
				entry["credit"] = round_currency(credit - signed_debit, currency)
				if entry.get("credit_in_account_currency") not in (None, ""):
					entry["credit_in_account_currency"] = entry["credit"]
			else:
				remainder = signed_debit - credit
				entry["credit"] = 0
				entry["credit_in_account_currency"] = 0
				entry["debit"] = round_currency(flt(entry.get("debit")) + remainder, currency)
				if entry.get("debit_in_account_currency") not in (None, ""):
					entry["debit_in_account_currency"] = entry["debit"]
		else:
			entry["debit"] = round_currency(flt(entry.get("debit")) + signed_debit, currency)
			if entry.get("debit_in_account_currency") not in (None, ""):
				entry["debit_in_account_currency"] = entry["debit"]
	else:
		credit_add = -signed_debit
		if flt(entry.get("debit")):
			debit = flt(entry.get("debit"))
			if debit >= credit_add:
				entry["debit"] = round_currency(debit - credit_add, currency)
				if entry.get("debit_in_account_currency") not in (None, ""):
					entry["debit_in_account_currency"] = entry["debit"]
			else:
				remainder = credit_add - debit
				entry["debit"] = 0
				entry["debit_in_account_currency"] = 0
				entry["credit"] = round_currency(flt(entry.get("credit")) + remainder, currency)
				if entry.get("credit_in_account_currency") not in (None, ""):
					entry["credit_in_account_currency"] = entry["credit"]
		else:
			entry["credit"] = round_currency(flt(entry.get("credit")) + credit_add, currency)
			if entry.get("credit_in_account_currency") not in (None, ""):
				entry["credit_in_account_currency"] = entry["credit"]


def _populate_round_off_dimensions(gle: dict, voucher_type: str, voucher_no: str, company: str) -> None:
	"""Copy voucher / Company default dimensions for mandatory accounting dimensions.

	Never sets or overrides cost_center — Company.round_off_cost_center is sole authority.
	"""
	from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import (
		get_accounting_dimensions,
		get_checks_for_pl_and_bs_accounts,
	)

	# Preserve Company Round Off Cost Center across dimension enrichment.
	locked_cost_center = gle.get("cost_center")

	dimensions = get_accounting_dimensions()
	meta = frappe.get_meta(voucher_type)
	if dimensions and all(meta.has_field(d) for d in dimensions) and voucher_no:
		values = frappe.db.get_value(voucher_type, voucher_no, dimensions, as_dict=True) or {}
		for dimension in dimensions:
			if dimension == "cost_center":
				continue
			if values.get(dimension):
				gle[dimension] = values.get(dimension)

	report_type = frappe.get_cached_value("Account", gle.get("account"), "report_type")
	for dimension in get_checks_for_pl_and_bs_accounts():
		if dimension.company != company:
			continue
		fieldname = dimension.fieldname
		if fieldname == "cost_center":
			continue
		if gle.get(fieldname):
			continue
		mandatory = (report_type == "Profit and Loss" and dimension.mandatory_for_pl) or (
			report_type == "Balance Sheet" and dimension.mandatory_for_bs
		)
		if mandatory:
			if not dimension.default_dimension:
				frappe.throw(
					_(
						"Mandatory accounting dimension {0} has no default for Round Off residual on {1}."
					).format(frappe.bold(dimension.label or fieldname), frappe.bold(company)),
					title=_("Missing Accounting Dimension"),
				)
			gle[fieldname] = dimension.default_dimension

	if locked_cost_center:
		gle["cost_center"] = locked_cost_center


def apply_irr_rate_rounding_residual_gl(doc, gl_map: list | None) -> list | None:
	"""Post-process ERPNext GL map: append Round Off residual, keep inventory authoritative.

	Manufacture / Repack: no IRR residual Round Off — value_difference uses Stock Adjustment.
	"""
	if not gl_map:
		return gl_map
	if not is_irr_company(doc.company):
		return gl_map
	if doc.doctype not in SUPPORTED_RESIDUAL_DOCTYPES:
		return gl_map
	if stock_entry_excludes_irr_residual_round_off(doc):
		strip_irr_rate_rounding_residual_gl(gl_map)
		return gl_map

	# Isolate zero-value transfer custom GL builder path.
	if doc.doctype == "Stock Entry":
		from erpnext_extensions.iran_accounting.zero_value_transfer import (
			_should_force_balanced_transfer_gl,
		)

		precision = 0
		if hasattr(doc, "get_debit_field_precision"):
			precision = doc.get_debit_field_precision()
		if _should_force_balanced_transfer_gl(doc, precision):
			return gl_map

	residuals = collect_document_residuals(doc)
	net_ro_debit = round_currency(
		sum(flt(r["round_off_debit"]) for r in residuals),
		get_company_currency(doc.company),
	)

	existing_ro = [
		e for e in gl_map if is_irr_rate_rounding_residual_gl(e, company=doc.company)
	]
	if not net_ro_debit:
		# Zero residual: drop any stale residual Round Off lines (should not exist).
		strip_irr_rate_rounding_residual_gl(gl_map)
		return gl_map
	if existing_ro:
		# Already applied — re-stamp Company masters (CCA must not have remapped them).
		for e in existing_ro:
			stamp_irr_residual_round_off_masters(e, doc.company)
		return gl_map

	cfg = resolve_company_round_off(doc.company, require=True)
	ccy = get_company_currency(doc.company)
	precision = 0 if (ccy or "").upper() == "IRR" else 2

	adjustable = _pick_adjustable_non_stock_leg(
		gl_map,
		doc.company,
		cfg["account"],
		protected_accounts=_protected_reclass_accounts(doc),
		reclass_magnitude=net_ro_debit,
	)
	if not adjustable:
		# No safe non-inventory partner (Stock Adj protected; Add Cost too small to reclass).
		# Keep vanilla GL; inventory amounts stay authoritative without inventing Round Off.
		return gl_map

	# Reclassify: Round Off gets net_ro_debit; adjustable gets the opposite.
	_apply_signed_debit_to_entry(adjustable, -net_ro_debit, precision, ccy)

	template = gl_map[0]
	row_trace = ", ".join(
		f"row {r.get('idx')} {r.get('item_code')} residual={r.get('residual')}" for r in residuals[:8]
	)
	ro = frappe._dict(
		{
			"account": cfg["account"],
			"cost_center": cfg["cost_center"],
			IRR_RATE_ROUNDING_RESIDUAL_MARKER: 1,
			"company": doc.company,
			"posting_date": template.get("posting_date") or doc.get("posting_date"),
			"voucher_type": doc.doctype,
			"voucher_no": doc.name,
			"remarks": f"{IRR_RATE_ROUNDING_RESIDUAL_REMARK}: {row_trace}",
			"is_opening": "No",
			"party_type": None,
			"party": None,
			"against_voucher_type": None,
			"against_voucher": None,
			"project": doc.get("project"),
			"debit": abs(net_ro_debit) if net_ro_debit > 0 else 0,
			"credit": abs(net_ro_debit) if net_ro_debit < 0 else 0,
			"debit_in_account_currency": abs(net_ro_debit) if net_ro_debit > 0 else 0,
			"credit_in_account_currency": abs(net_ro_debit) if net_ro_debit < 0 else 0,
			"debit_in_transaction_currency": abs(net_ro_debit) if net_ro_debit > 0 else 0,
			"credit_in_transaction_currency": abs(net_ro_debit) if net_ro_debit < 0 else 0,
		}
	)
	if template.get("finance_book"):
		ro["finance_book"] = template.get("finance_book")
	_populate_round_off_dimensions(ro, doc.doctype, doc.name, doc.company)
	# Sole authority after any dimension enrichment — never inherit row/leg/CCA/dimension CC.
	stamp_irr_residual_round_off_masters(ro, doc.company)
	gl_map.append(ro)
	return gl_map


def expected_round_off_gl_totals(doc) -> dict[str, float]:
	"""Expected Round Off debit/credit from document residuals (for validators/tests)."""
	residuals = collect_document_residuals(doc)
	ccy = get_company_currency(doc.company)
	net = round_currency(sum(flt(r["round_off_debit"]) for r in residuals), ccy)
	return {
		"net_signed_debit": flt(net),
		"debit": abs(flt(net)) if flt(net) > 0 else 0.0,
		"credit": abs(flt(net)) if flt(net) < 0 else 0.0,
		"residuals": residuals,
	}


def fetch_irr_residual_gl_rows(voucher_type: str, voucher_no: str) -> list[dict]:
	rows = frappe.get_all(
		"GL Entry",
		filters={"voucher_type": voucher_type, "voucher_no": voucher_no, "is_cancelled": 0},
		fields=["name", "account", "debit", "credit", "cost_center", "remarks", "company"],
	)
	company = rows[0].get("company") if rows else None
	return [r for r in rows if is_irr_rate_rounding_residual_gl(r, company=company)]


def rebuild_irr_rate_rounding_residual_after_repost(doc) -> list[str]:
	"""After RIV/RAL amount/SLE reconcile: remake GL so residual Round Off is idempotent."""
	actions: list[str] = []
	if not is_irr_company(doc.company) or doc.docstatus != 1:
		return actions
	if doc.doctype not in SUPPORTED_RESIDUAL_DOCTYPES:
		return actions
	if not cint(frappe.get_cached_value("Company", doc.company, "enable_perpetual_inventory")):
		# ERPNext may use different flag; still attempt remake when make_gl_entries exists.
		pass

	if not hasattr(doc, "make_gl_entries"):
		return actions

	# Remake GL from document (cancels prior + posts fresh ERPNext + residual layer).
	from erpnext.accounts.general_ledger import make_reverse_gl_entries

	make_reverse_gl_entries(voucher_type=doc.doctype, voucher_no=doc.name)
	actions.append("reversed_gl_for_residual_rebuild")
	doc.make_gl_entries()
	actions.append("remade_gl_with_irr_rate_residual")
	return actions
