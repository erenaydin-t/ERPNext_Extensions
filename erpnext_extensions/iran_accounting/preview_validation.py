# Copyright (c) 2026, ERPNext Extensions contributors
"""Desk Accounting Ledger Preview validation (server-side, same API as Desk)."""

from __future__ import annotations

import frappe
from frappe.utils import flt

from erpnext_extensions.iran_accounting.rounding import (
	get_company_currency,
	get_currency_precision,
	is_irr_company,
	round_currency,
)
from erpnext_extensions.iran_accounting.validation import (
	amount_is_fractional,
	gl_debit_credit_totals,
	is_doubled_gl,
	stock_adj_round_off_rows,
)


def get_accounting_ledger_preview_rows(doc) -> dict:
	"""Build preview via ERPNext get_accounting_ledger_preview (no db.rollback)."""
	from erpnext.controllers.stock_controller import get_accounting_ledger_preview

	if isinstance(doc, str):
		doc = frappe.get_doc("Stock Entry", doc)
	doc.run_method("before_gl_preview")
	filters = frappe._dict(company=doc.company, include_dimensions=1)
	gl_columns, gl_data = get_accounting_ledger_preview(doc, filters)
	return {"gl_columns": gl_columns, "gl_data": gl_data}


def _preview_column_indices(gl_columns: list) -> tuple[int | None, int | None, int | None]:
	debit_i = credit_i = account_i = None
	for i, col in enumerate(gl_columns or []):
		label = (col.get("name") or col.get("label") or "").lower()
		if "debit" in label and debit_i is None:
			debit_i = i
		if "credit" in label and credit_i is None:
			credit_i = i
		if label == "account" or (
			label.endswith("account") and "against" not in label and "voucher" not in label
		):
			if account_i is None:
				account_i = i
	return debit_i, credit_i, account_i


def preview_rows_to_gl_like(gl_columns: list, gl_data: list) -> list[dict]:
	di, ci, ai = _preview_column_indices(gl_columns)
	out = []
	for row in gl_data or []:
		if not isinstance(row, (list, tuple)):
			continue
		entry = {
			"debit": flt(row[di]) if di is not None and len(row) > di else 0,
			"credit": flt(row[ci]) if ci is not None and len(row) > ci else 0,
			"account": row[ai] if ai is not None and len(row) > ai else None,
		}
		out.append(entry)
	return out


def merge_preview_gl_like(gl_like: list[dict]) -> list[dict]:
	"""Merge preview rows by account (Desk preview may list duplicate legs before submit merge)."""
	from collections import defaultdict

	buckets: dict[str | None, dict] = defaultdict(lambda: {"debit": 0.0, "credit": 0.0, "account": None})
	for row in gl_like:
		acct = row.get("account")
		buckets[acct]["account"] = acct
		buckets[acct]["debit"] += flt(row.get("debit"))
		buckets[acct]["credit"] += flt(row.get("credit"))
	return list(buckets.values())


def validate_accounting_ledger_preview(doc, company: str) -> dict:
	"""Validate preview for zero-value transfer rules and IRR decimals."""
	if isinstance(doc, str):
		doc = frappe.get_doc("Stock Entry", doc)
	preview = get_accounting_ledger_preview_rows(doc)
	gl_columns = preview.get("gl_columns") or []
	gl_data = preview.get("gl_data") or []
	gl_like = preview_rows_to_gl_like(gl_columns, gl_data)
	purposes = ("Material Transfer", "Material Transfer for Manufacture", "Send to Subcontractor")
	is_zero = doc.purpose in purposes and flt(doc.value_difference) == 0
	if is_zero:
		gl_like = merge_preview_gl_like(gl_like)
	debit_total, credit_total = gl_debit_credit_totals(gl_like)

	cur = get_company_currency(company)
	expected_in = round_currency(doc.total_incoming_value, cur)
	expected_out = round_currency(doc.total_outgoing_value, cur)

	adj = stock_adj_round_off_rows(gl_like, company)
	# Also match account name strings in preview
	for row in gl_like:
		acct = (row.get("account") or "").lower()
		if "stock adjustment" in acct or "round off" in acct:
			if flt(row.get("debit")) or flt(row.get("credit")):
				adj.append(row)

	preview_irr_decimals = []
	if is_irr_company(company):
		for row in gl_like:
			for f in ("debit", "credit"):
				val = row.get(f)
				if val and amount_is_fractional(val, cur):
					preview_irr_decimals.append({f: val, "account": row.get("account")})

	totals_match = flt(debit_total) == flt(expected_in) and flt(credit_total) == flt(expected_out)
	if is_zero and not totals_match:
		tol = 1 if get_currency_precision(cur) == 0 else 0.01
		totals_match = (
			abs(flt(debit_total) - flt(expected_in)) <= tol
			and abs(flt(credit_total) - flt(expected_out)) <= tol
			and flt(debit_total) == flt(credit_total)
		)
	no_double = not is_doubled_gl(debit_total, expected_in) and not is_doubled_gl(credit_total, expected_out)
	if (
		is_zero
		and totals_match
		and (is_doubled_gl(debit_total, expected_in) or is_doubled_gl(credit_total, expected_out))
	):
		no_double = flt(debit_total) == flt(expected_in) and flt(credit_total) == flt(expected_out)
	no_adj = not adj

	purposes = ("Material Transfer", "Material Transfer for Manufacture", "Send to Subcontractor")
	is_zero = doc.purpose in purposes and flt(doc.value_difference) == 0

	preview_ok = totals_match and no_double and (not is_zero or no_adj) and not preview_irr_decimals

	return {
		"preview_ok": preview_ok,
		"ui_api_ok": preview_ok,
		"debit_total": debit_total,
		"credit_total": credit_total,
		"expected_in": expected_in,
		"expected_out": expected_out,
		"no_adjustment_ok": no_adj,
		"no_double_ok": no_double,
		"preview_irr_decimals": preview_irr_decimals,
		"gl_columns": gl_columns,
		"gl_data": gl_data,
		"gl_like": gl_like,
	}


def preview_gl_signature(preview: dict) -> tuple:
	gl_like = preview_rows_to_gl_like(preview.get("gl_columns"), preview.get("gl_data"))
	sig = []
	for row in sorted(gl_like, key=lambda r: (r.get("account") or "", r.get("debit"), r.get("credit"))):
		sig.append((row.get("account"), flt(row.get("debit")), flt(row.get("credit"))))
	return tuple(sig)


def submitted_gl_signature(voucher_no: str) -> tuple:
	from erpnext_extensions.iran_accounting.sql_validation import sql_get_gl_rows

	rows = sql_get_gl_rows("Stock Entry", voucher_no)
	sig = []
	for row in rows:
		sig.append((row.get("account"), flt(row.get("debit")), flt(row.get("credit"))))
	return tuple(sorted(sig))
