# Copyright (c) 2026, ERPNext Extensions contributors
"""Read-only Stock Entry row / SLE / GL drift diagnostics (API + server)."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import frappe
from frappe.utils import flt

from erpnext_extensions.iran_accounting.domain.currency import get_company_currency, is_irr_company
from erpnext_extensions.iran_accounting.domain.stock_entry_ledger_contract import _gl_stock_account_net
from erpnext_extensions.iran_accounting.domain.stock_entry_sync import (
	signed_movement_from_row_amount,
	stock_entry_row_amount,
	sum_stock_entry_row_amounts,
)
from erpnext_extensions.iran_accounting.validation import (
	fetch_gl_rows,
	fetch_sle_rows,
	gl_debit_credit_totals,
)


def _round_irr_amount(qty, rate) -> int:
	raw = Decimal(str(qty)) * Decimal(str(rate))
	return int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _resource_url(base_url: str, doctype: str, name: str | None = None) -> str:
	path = "/api/resource/" + urllib.parse.quote(doctype, safe="")
	if name:
		path += "/" + urllib.parse.quote(name, safe="")
	return base_url.rstrip("/") + path


def _api_get(base_url: str, api_key: str, api_secret: str, path: str, params: dict | None = None) -> dict:
	url = base_url.rstrip("/") + path
	if params:
		url += "?" + urllib.parse.urlencode(params)
	req = urllib.request.Request(
		url,
		headers={
			"Authorization": f"token {api_key}:{api_secret}",
			"Accept": "application/json",
		},
	)
	with urllib.request.urlopen(req, timeout=120) as resp:
		return json.loads(resp.read().decode())


def _simulate_cc_allocation_loss(amounts: list[float], percentages: list[float]) -> dict:
	"""Mirror ERPNext flt(amt * pct/100, 0) per split (IRR)."""
	losses = []
	total = 0
	for amt in amounts:
		splits = [
			int(Decimal(str(amt * p / 100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
			for p in percentages
		]
		loss = amt - sum(splits)
		losses.append(loss)
		total += sum(splits)
	return {
		"split_sums": [amt - loss for amt, loss in zip(amounts, losses)],
		"per_row_loss": losses,
		"total_after_split": total,
		"total_loss": sum(losses),
	}


def _fetch_cost_center_allocation_hint(
	base_url: str, api_key: str, api_secret: str, company: str, main_cc: str, posting_date: str
) -> dict | None:
	filters = json.dumps(
		[
			["company", "=", company],
			["main_cost_center", "=", main_cc],
			["docstatus", "=", 1],
			["valid_from", "<=", posting_date],
		]
	)
	try:
		resp = _api_get(
			base_url,
			api_key,
			api_secret,
			"/api/resource/" + urllib.parse.quote("Cost Center Allocation"),
			{
				"fields": json.dumps(["name", "main_cost_center", "valid_from"]),
				"filters": filters,
				"order_by": "valid_from desc",
				"limit_page_length": 1,
			},
		)
		rows = resp.get("data") or []
		if not rows:
			return None
		doc = _api_get(
			base_url,
			api_key,
			api_secret,
			_resource_url(base_url, "Cost Center Allocation", rows[0]["name"]).replace(
				base_url.rstrip("/"), ""
			),
		)
		data = doc.get("data") or doc
		pcts = [float(r.get("percentage") or 0) for r in (data.get("allocation_percentages") or [])]
		return {"name": data.get("name"), "percentages": pcts, "main_cost_center": main_cc}
	except Exception:
		return None


def _warehouse_account_map(doc) -> list[dict]:
	rows = []
	seen = set()
	for row in doc.get("items") or []:
		for field in ("s_warehouse", "t_warehouse"):
			wh = row.get(field)
			if not wh or wh in seen:
				continue
			seen.add(wh)
			rows.append(
				{
					"warehouse": wh,
					"account": frappe.db.get_value("Warehouse", wh, "account"),
					"company": frappe.db.get_value("Warehouse", wh, "company"),
				}
			)
	return rows


def compute_gl_submit_pipeline_counts(doc) -> dict[str, Any]:
	"""Mirror ERPNext make_gl_entries → process_gl_map stages (read-only, no persist)."""
	import copy

	import erpnext.accounts.general_ledger as gl_mod

	if doc.docstatus == 2:
		return {}

	inventory_account_map = doc.get_inventory_account_map()
	raw = doc.get_gl_entries(inventory_account_map) or []
	raw_count = len(raw)
	if not raw_count:
		return {
			"RAW_GL_COUNT": 0,
			"AFTER_DIMENSION_OFFSET_COUNT": 0,
			"AFTER_COST_CENTER_ALLOCATION_COUNT": 0,
			"AFTER_MERGE_COUNT": 0,
			"FINAL_GL_COUNT": 0,
			"WOULD_THROW_INCORRECT_GL_COUNT": False,
		}

	precision = doc.get_debit_field_precision()
	gl_map = copy.deepcopy(raw)
	try:
		gl_mod.make_acc_dimensions_offsetting_entry(gl_map)
	except Exception:
		pass
	after_offset = len(gl_map)

	gl_map = gl_mod.distribute_gl_based_on_cost_center_allocation(gl_map, precision)
	after_cca = len(gl_map)
	gl_map = gl_mod.merge_similar_entries(gl_map, precision)
	after_merge = len(gl_map)
	final = gl_mod.toggle_debit_credit_if_negative(gl_map)
	final_count = len(final)

	return {
		"RAW_GL_COUNT": raw_count,
		"AFTER_DIMENSION_OFFSET_COUNT": after_offset,
		"AFTER_COST_CENTER_ALLOCATION_COUNT": after_cca,
		"AFTER_MERGE_COUNT": after_merge,
		"FINAL_GL_COUNT": final_count,
		"WOULD_THROW_INCORRECT_GL_COUNT": bool(final) and final_count <= 1,
		"EXACT_THROW_LOCATION": "erpnext/accounts/general_ledger.py:make_gl_entries (len(gl_map)<=1 after process_gl_map)",
	}


def _preview_gl_stock_net(doc) -> tuple[list[dict], float]:
	"""In-process GL map (not persisted) — same path as submit."""
	from erpnext.accounts.general_ledger import process_gl_map

	inventory_account_map = doc.get_inventory_account_map()
	gl_list = doc.get_gl_entries(inventory_account_map)
	precision = doc.get_debit_field_precision()
	gl_map = process_gl_map(gl_list, precision=precision)
	rows = []
	for entry in gl_map:
		rows.append(
			{
				"account": entry.account,
				"debit": flt(entry.debit),
				"credit": flt(entry.credit),
				"cost_center": entry.get("cost_center"),
				"against": entry.get("against"),
			}
		)
	stock_net = _gl_stock_account_net(rows, doc.company)
	return rows, stock_net


def analyze_stock_entry_ledger_drift(voucher_no: str) -> dict[str, Any]:
	"""Server-side read-only analysis (draft or submitted)."""
	if not frappe.db.exists("Stock Entry", voucher_no):
		frappe.throw(f"Stock Entry {voucher_no} not found")

	doc = frappe.get_doc("Stock Entry", voucher_no)
	company = doc.company
	ccy = get_company_currency(company)
	purpose = doc.purpose

	item_rows = []
	row_total = 0.0
	for row in sorted(doc.items, key=lambda r: r.idx or 0):
		qty = flt(row.qty)
		rate = row.basic_rate if row.basic_rate not in (None, "") else row.valuation_rate
		expected = _round_irr_amount(qty, rate) if qty and rate not in (None, "") else 0
		stored = flt(row.amount)
		norm = stock_entry_row_amount(row, company)
		if row.s_warehouse and purpose == "Material Issue":
			row_total += norm
		item_rows.append(
			{
				"idx": row.idx,
				"item_code": row.item_code,
				"name": row.name,
				"qty": qty,
				"transfer_qty": flt(row.transfer_qty),
				"conversion_factor": flt(row.conversion_factor),
				"basic_rate": flt(rate),
				"expected_amount": expected,
				"stored_amount": stored,
				"normalized_amount": norm,
				"delta_row": stored - expected,
				"cost_center": row.cost_center,
				"s_warehouse": row.s_warehouse,
				"t_warehouse": row.t_warehouse,
			}
		)

	sle_rows_db = fetch_sle_rows("Stock Entry", voucher_no)
	sle_sum = sum(flt(s.get("stock_value_difference")) for s in sle_rows_db)
	sle_abs = sum(abs(flt(s.get("stock_value_difference"))) for s in sle_rows_db)

	sle_mapped = []
	for sle in sle_rows_db:
		vd = sle.get("voucher_detail_no")
		item = next((r for r in item_rows if r["name"] == vd), None)
		exp_sle = 0.0
		if item:
			exp_sle = signed_movement_from_row_amount(item["normalized_amount"], flt(sle.get("actual_qty")))
		sle_mapped.append(
			{
				**sle,
				"expected_sle": exp_sle,
				"sle_delta": flt(sle.get("stock_value_difference")) - exp_sle,
			}
		)

	gl_rows_db = fetch_gl_rows("Stock Entry", voucher_no)
	gl_stock_net_db = _gl_stock_account_net(gl_rows_db, company) if gl_rows_db else 0.0

	preview_rows: list[dict] = []
	gl_stock_net_preview = 0.0
	preview_error = None
	if is_irr_company(company):
		try:
			doc.run_method("before_gl_preview")
			preview_rows, gl_stock_net_preview = _preview_gl_stock_net(doc)
		except Exception as exc:
			preview_error = str(exc)

	gl_stock_net = gl_stock_net_db if gl_rows_db else gl_stock_net_preview
	sle_total = abs(sle_sum) if sle_sum else row_total
	gl_total = abs(gl_stock_net)

	cc_hint = None
	cc_sim = None
	main_cc = doc.items[0].cost_center if doc.items else None
	if main_cc and is_irr_company(company):
		from erpnext.accounts.general_ledger import get_cost_center_allocation_data

		alloc = get_cost_center_allocation_data(company, doc.posting_date, main_cc)
		if alloc:
			pcts = [float(p) for _, p in alloc]
			amounts = [r["normalized_amount"] for r in item_rows if r["normalized_amount"]]
			cc_sim = _simulate_cc_allocation_loss(amounts, pcts)
			cc_hint = {"main_cost_center": main_cc, "percentages": pcts, "allocation_doc": alloc}

	root_cause = None
	if gl_total and sle_total and gl_total != sle_total:
		if cc_sim and cc_sim.get("total_loss") == sle_total - gl_total:
			root_cause = (
				"Cost Center Allocation splits GL legs with flt(amt×pct/100, 0); "
				f"rounding drops {int(cc_sim['total_loss'])} IRR vs row/SLE total "
				"(SLE is not split by cost center)."
			)
		elif row_total == sle_total:
			root_cause = (
				"GL stock net diverges from SLE while row amounts match SLE — inspect GL merge/split path."
			)
		else:
			root_cause = "Row/SLE mismatch — inspect SLE sync before GL."

	status = "PASS"
	if row_total != sle_total or (gl_total and gl_total != sle_total):
		status = "FAIL"

	gl_pipeline = {}
	pipeline_error = None
	force_balanced = None
	if is_irr_company(company) and doc.docstatus != 2:
		try:
			from erpnext_extensions.iran_accounting import zero_value_transfer as zvt

			force_balanced = zvt._should_force_balanced_transfer_gl(doc, doc.get_debit_field_precision())
			if doc.docstatus == 0:
				doc.run_method("before_gl_preview")
			gl_pipeline = compute_gl_submit_pipeline_counts(doc)
		except Exception as exc:
			pipeline_error = str(exc)

	return {
		"status": status,
		"voucher_no": voucher_no,
		"docstatus": doc.docstatus,
		"purpose": purpose,
		"company": company,
		"currency": ccy,
		"posting_date": str(doc.posting_date),
		"total_incoming_value": flt(doc.total_incoming_value),
		"total_outgoing_value": flt(doc.total_outgoing_value),
		"value_difference": flt(doc.value_difference),
		"force_balanced_transfer_gl": force_balanced,
		"warehouse_accounts": _warehouse_account_map(doc),
		"row_total": row_total,
		"sle_total": sle_total,
		"gl_total": gl_total,
		"delta_gl_vs_sle": gl_total - sle_total,
		"delta_row_vs_sle": row_total - sle_total,
		"delta_row_vs_gl": row_total - gl_total,
		"item_rows": item_rows,
		"sle_rows": sle_mapped,
		"gl_rows_persisted": gl_rows_db,
		"gl_rows_preview": preview_rows,
		"gl_preview_error": preview_error,
		"gl_pipeline": gl_pipeline,
		"gl_pipeline_error": pipeline_error,
		"cost_center_allocation": cc_hint,
		"cost_center_allocation_simulation": cc_sim,
		"root_cause": root_cause,
		"fix_recommendation": (
			"Patch IRR cost center GL distribution to absorb split rounding residual per leg "
			"(domain/gl_cost_center_allocation.py) so Σ splits = original debit/credit; "
			"SLE already uses row.amount."
			if root_cause and "Cost Center Allocation" in root_cause
			else "Align GL generation with row.amount after identifying layer mismatch."
		),
		"safe_to_submit_after_fix": "YES" if root_cause and "Cost Center Allocation" in root_cause else "NO",
	}


@frappe.whitelist()
def debug_stock_entry_ledger_drift(voucher_no: str) -> dict[str, Any]:
	"""Whitelisted read-only diagnostic for production Desk/API."""
	return analyze_stock_entry_ledger_drift(voucher_no)


def debug_stock_entry_ledger_drift_api(
	base_url: str,
	api_key: str,
	api_secret: str,
	voucher_no: str,
) -> dict[str, Any]:
	"""REST-only diagnostic (no GL preview if extension method not deployed)."""
	base_url = base_url.rstrip("/")
	user = _api_get(base_url, api_key, api_secret, "/api/method/frappe.auth.get_logged_user")
	logged_user = user.get("message")

	versions = None
	try:
		versions = _api_get(
			base_url, api_key, api_secret, "/api/method/frappe.utils.change_log.get_versions"
		).get("message")
	except Exception:
		pass

	try:
		server = _api_post_json(
			base_url,
			api_key,
			api_secret,
			"erpnext_extensions.iran_accounting.stock_gl_consistency.debug_stock_entry_ledger_drift_api.debug_stock_entry_ledger_drift",
			{"voucher_no": voucher_no},
		)
		out = server.get("message") or server
		out["auth_user"] = logged_user
		out["versions"] = versions
		return out
	except Exception:
		pass

	return _api_only_report(base_url, api_key, api_secret, voucher_no, logged_user, versions)


def _api_post_json(base_url: str, api_key: str, api_secret: str, method: str, data: dict) -> dict:
	url = base_url.rstrip("/") + "/api/method/" + method
	body = json.dumps(data).encode()
	req = urllib.request.Request(
		url,
		data=body,
		method="POST",
		headers={
			"Authorization": f"token {api_key}:{api_secret}",
			"Accept": "application/json",
			"Content-Type": "application/json",
		},
	)
	with urllib.request.urlopen(req, timeout=120) as resp:
		return json.loads(resp.read().decode())


def _api_only_report(
	base_url: str,
	api_key: str,
	api_secret: str,
	voucher_no: str,
	logged_user: str | None,
	versions: Any,
) -> dict[str, Any]:
	se = _api_get(
		base_url,
		api_key,
		api_secret,
		_resource_url(base_url, "Stock Entry", voucher_no).replace(base_url, ""),
	)
	data = se.get("data") or se
	purpose = data.get("purpose")
	company = data.get("company")
	posting_date = str(data.get("posting_date") or "")

	item_rows = []
	row_total = 0.0
	for row in sorted(data.get("items") or [], key=lambda x: x.get("idx") or 0):
		qty = float(row.get("qty") or 0)
		rate = row.get("basic_rate")
		if rate in (None, "") and row.get("valuation_rate") not in (None, ""):
			rate = row.get("valuation_rate")
		expected = _round_irr_amount(qty, rate) if qty and rate not in (None, "") else 0
		stored = float(row.get("amount") or 0)
		if row.get("s_warehouse") and purpose == "Material Issue":
			row_total += expected
		item_rows.append(
			{
				"idx": row.get("idx"),
				"item_code": row.get("item_code"),
				"qty": qty,
				"basic_rate": rate,
				"expected_amount": expected,
				"stored_amount": stored,
				"delta_row": stored - expected,
				"cost_center": row.get("cost_center"),
			}
		)

	sle_fields = json.dumps(
		["name", "stock_value_difference", "voucher_detail_no", "actual_qty", "is_cancelled"]
	)
	sle_resp = _api_get(
		base_url,
		api_key,
		api_secret,
		"/api/resource/" + urllib.parse.quote("Stock Ledger Entry"),
		{
			"fields": sle_fields,
			"filters": json.dumps([["voucher_type", "=", "Stock Entry"], ["voucher_no", "=", voucher_no]]),
			"limit_page_length": 500,
		},
	)
	sles = [s for s in (sle_resp.get("data") or []) if not s.get("is_cancelled")]
	sle_sum = sum(float(s.get("stock_value_difference") or 0) for s in sles)
	sle_total = abs(sle_sum) if sles else row_total

	gl_fields = json.dumps(["account", "debit", "credit", "is_cancelled"])
	gl_resp = _api_get(
		base_url,
		api_key,
		api_secret,
		"/api/resource/" + urllib.parse.quote("GL Entry"),
		{
			"fields": gl_fields,
			"filters": json.dumps(
				[
					["voucher_type", "=", "Stock Entry"],
					["voucher_no", "=", voucher_no],
					["is_cancelled", "=", 0],
				]
			),
			"limit_page_length": 500,
		},
	)
	gls = gl_resp.get("data") or []
	stock_accounts: set[str] = set()
	for g in gls:
		acc = g.get("account")
		if not acc:
			continue
		try:
			ad = _api_get(
				base_url,
				api_key,
				api_secret,
				_resource_url(base_url, "Account", acc).replace(base_url, ""),
			).get("data")
			if ad and ad.get("account_type") == "Stock":
				stock_accounts.add(acc)
		except Exception:
			pass
	gl_stock = sum(
		float(g.get("debit") or 0) - float(g.get("credit") or 0)
		for g in gls
		if g.get("account") in stock_accounts
	)
	gl_total = abs(gl_stock)

	cc_sim = None
	root_cause = None
	main_cc = item_rows[0]["cost_center"] if item_rows else None
	if main_cc and data.get("docstatus") == 0 and not gls:
		hint = _fetch_cost_center_allocation_hint(
			base_url, api_key, api_secret, company, main_cc, posting_date
		)
		if hint and hint.get("percentages"):
			amounts = [r["expected_amount"] for r in item_rows]
			cc_sim = _simulate_cc_allocation_loss(amounts, hint["percentages"])
			if not gl_total:
				gl_total = cc_sim["total_after_split"]

	if row_total == sle_total and gl_total and gl_total != sle_total:
		if cc_sim and flt(cc_sim.get("total_loss")) == sle_total - gl_total:
			root_cause = (
				"Cost Center Allocation (valid from posting date) rounds each GL split with "
				f"flt(×pct/100, 0); simulated loss {cc_sim['total_loss']} IRR matches "
				"|GL stock| vs |Σ SLE| gap. Submit rolls back so API shows no GL/SLE."
			)

	status = "FAIL" if (row_total != sle_total or gl_total != sle_total) else "PASS"

	return {
		"status": status,
		"voucher_no": voucher_no,
		"auth_user": logged_user,
		"versions": versions,
		"docstatus": data.get("docstatus"),
		"purpose": purpose,
		"row_total": row_total,
		"sle_total": sle_total,
		"gl_total": gl_total,
		"delta_gl_vs_sle": gl_total - sle_total,
		"delta_row_vs_sle": row_total - sle_total,
		"delta_row_vs_gl": row_total - gl_total,
		"item_rows": item_rows,
		"sle_rows": sles,
		"gl_rows_persisted": gls,
		"cost_center_allocation_simulation": cc_sim,
		"root_cause": root_cause,
		"fix_recommendation": (
			"Deploy IRR cost-center split residual absorption "
			"(gl_cost_center_allocation.distribute_gl_based_on_cost_center_allocation_irr) "
			"before re-submitting."
			if root_cause
			else None
		),
		"safe_to_submit_after_fix": "YES" if root_cause else "UNKNOWN",
		"note": "Draft failed submit: persisted GL/SLE empty; gl_total may be simulated from CC allocation."
		if data.get("docstatus") == 0 and not gls
		else None,
	}


def investigate_stock_entry_from_env() -> dict[str, Any]:
	"""Bench CLI helper: reads ERP_BASE_URL, ERP_API_KEY, ERP_API_SECRET, optional STE_VOUCHER."""
	import os

	voucher = os.environ.get("STE_VOUCHER", "MAT-STE-2026-03077")
	base = (os.environ.get("ERP_BASE_URL") or "").rstrip("/")
	key = os.environ.get("ERP_API_KEY") or ""
	secret = os.environ.get("ERP_API_SECRET") or ""
	if not base or not key or not secret:
		return {"error": "missing_env", "required": ["ERP_BASE_URL", "ERP_API_KEY", "ERP_API_SECRET"]}

	return debug_stock_entry_ledger_drift_api(base, key, secret, voucher)

