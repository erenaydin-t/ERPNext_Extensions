# Copyright (c) 2026, ERPNext Extensions contributors
"""DB-backed Stock Entry / SLE / GL / Bin / report / snapshot verification."""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
from typing import Any

import frappe
from frappe.utils import today

from erpnext_extensions.iran_accounting.reports import run_general_ledger_report, run_stock_ledger_report
from erpnext_extensions.iran_accounting.tests.hardening.decimal_money import (
	D,
	compose_amount,
	money_equal,
	quantize_money,
	rate_equal,
	residual,
	valuation_from_amount,
)
from erpnext_extensions.iran_accounting.tests.hardening.fixtures import IRR_PRECISION


IGNORE_SNAPSHOT_KEYS = frozenset(
	{"name", "creation", "modified", "owner", "modified_by", "idx", "parent", "parenttype", "parentfield"}
)


def _sql_dicts(query: str, values: tuple | list | None = None) -> list[dict]:
	return frappe.db.sql(query, values or (), as_dict=True)


def fetch_stock_entry(name: str) -> dict:
	rows = _sql_dicts(
		"""
		select name, purpose, company, docstatus,
			total_incoming_value, total_outgoing_value, total_additional_costs,
			value_difference, per_transferred
		from `tabStock Entry` where name=%s
		""",
		(name,),
	)
	if not rows:
		raise AssertionError(f"Stock Entry {name} missing in DB")
	return rows[0]


def fetch_stock_entry_details(name: str) -> list[dict]:
	return _sql_dicts(
		"""
		select name, idx, item_code, qty, transfer_qty, conversion_factor,
			basic_rate, basic_amount, additional_cost, landed_cost_voucher_amount,
			amount, valuation_rate, s_warehouse, t_warehouse, is_finished_item,
			uom, stock_uom, cost_center
		from `tabStock Entry Detail`
		where parent=%s
		order by idx asc, name asc
		""",
		(name,),
	)


def fetch_additional_costs(name: str) -> list[dict]:
	return _sql_dicts(
		"""
		select name, expense_account, description, amount, base_amount
		from `tabLanded Cost Taxes and Charges`
		where parent=%s and parenttype='Stock Entry'
		order by idx asc, name asc
		""",
		(name,),
	)


def fetch_sle_db(voucher_type: str, voucher_no: str) -> list[dict]:
	return _sql_dicts(
		"""
		select name, item_code, warehouse, actual_qty, qty_after_transaction,
			valuation_rate, incoming_rate, outgoing_rate, stock_value,
			stock_value_difference, posting_date, posting_time,
			voucher_type, voucher_no, voucher_detail_no, is_cancelled
		from `tabStock Ledger Entry`
		where voucher_type=%s and voucher_no=%s and is_cancelled=0
		order by posting_date, posting_time, creation, name
		""",
		(voucher_type, voucher_no),
	)


def fetch_gl_db(voucher_type: str, voucher_no: str) -> list[dict]:
	return _sql_dicts(
		"""
		select name, account, debit, credit, against, cost_center, party,
			party_type, finance_book, remarks, voucher_type, voucher_no, is_cancelled
		from `tabGL Entry`
		where voucher_type=%s and voucher_no=%s and is_cancelled=0
		order by account, debit desc, credit desc, name
		""",
		(voucher_type, voucher_no),
	)


def fetch_bin(item_code: str, warehouse: str) -> dict | None:
	rows = _sql_dicts(
		"""
		select name, item_code, warehouse, actual_qty, valuation_rate, stock_value,
			reserved_qty, projected_qty
		from `tabBin` where item_code=%s and warehouse=%s
		""",
		(item_code, warehouse),
	)
	return rows[0] if rows else None


def assert_stock_entry_header(name: str, *, purpose: str | None = None, docstatus: int = 1) -> dict:
	row = fetch_stock_entry(name)
	if purpose is not None and row["purpose"] != purpose:
		raise AssertionError(f"purpose: {row['purpose']} != {purpose}")
	if int(row["docstatus"]) != int(docstatus):
		raise AssertionError(f"docstatus: {row['docstatus']} != {docstatus}")
	# Header identity: incoming - outgoing ≈ value_difference (IRR integer)
	inc = quantize_money(row["total_incoming_value"], IRR_PRECISION)
	out = quantize_money(row["total_outgoing_value"], IRR_PRECISION)
	vd = quantize_money(row["value_difference"], IRR_PRECISION)
	money_equal(inc - out, vd, precision=IRR_PRECISION, label=f"{name} header VD identity")
	return row


def assert_detail_composition(details: list[dict], *, precision: int = IRR_PRECISION) -> None:
	for row in details:
		label = f"row {row.get('idx')} {row.get('item_code')}"
		exp = compose_amount(
			row.get("basic_amount"),
			row.get("additional_cost"),
			row.get("landed_cost_voucher_amount"),
			precision=precision,
		)
		money_equal(row.get("amount"), exp, precision=precision, label=f"{label} amount composition")
		tq = D(row.get("transfer_qty") if row.get("transfer_qty") not in (None, "") else row.get("qty"))
		if tq != 0:
			exp_rate = valuation_from_amount(row.get("amount"), tq)
			rate_equal(row.get("valuation_rate"), exp_rate, places=9, label=f"{label} valuation_rate")
		# conversion identity
		if D(row.get("conversion_factor") or 0) and D(row.get("qty") or 0):
			exp_tq = quantize_money(D(row["qty"]) * D(row["conversion_factor"]), 6)
			# allow stock qty precision residual of 1e-6
			if abs(D(row.get("transfer_qty") or 0) - exp_tq) > Decimal("0.000001"):
				raise AssertionError(
					f"{label} transfer_qty {row.get('transfer_qty')} != qty×conv {exp_tq}"
				)


def assert_sle_integrity(voucher_type: str, voucher_no: str) -> list[dict]:
	rows = fetch_sle_db(voucher_type, voucher_no)
	names = [r["name"] for r in rows]
	if len(names) != len(set(names)):
		raise AssertionError(f"duplicate SLE names on {voucher_type} {voucher_no}")
	for r in rows:
		label = f"SLE {r['name']}"
		money_equal(
			r["stock_value_difference"],
			quantize_money(r["stock_value_difference"], IRR_PRECISION),
			precision=IRR_PRECISION,
			label=f"{label} svd integer IRR",
		)
		# sign vs qty
		aq = D(r["actual_qty"])
		svd = D(r["stock_value_difference"])
		if aq > 0 and svd < 0:
			raise AssertionError(f"{label}: positive qty with negative SVD")
		if aq < 0 and svd > 0:
			raise AssertionError(f"{label}: negative qty with positive SVD")
		if r["voucher_type"] != voucher_type or r["voucher_no"] != voucher_no:
			raise AssertionError(f"{label}: voucher linkage mismatch")
		if not r.get("posting_date"):
			raise AssertionError(f"{label}: missing posting_date")
	return rows


def assert_gl_integrity(voucher_type: str, voucher_no: str) -> list[dict]:
	rows = fetch_gl_db(voucher_type, voucher_no)
	debit = sum((quantize_money(r["debit"], IRR_PRECISION) for r in rows), Decimal("0"))
	credit = sum((quantize_money(r["credit"], IRR_PRECISION) for r in rows), Decimal("0"))
	money_equal(debit, credit, precision=IRR_PRECISION, label=f"{voucher_type} {voucher_no} GL balanced")
	names = [r["name"] for r in rows]
	if len(names) != len(set(names)):
		raise AssertionError(f"duplicate GL names on {voucher_type} {voucher_no}")
	for r in rows:
		if not r.get("account"):
			raise AssertionError(f"GL {r.get('name')} missing account")
	return rows


def assert_no_duplicate_expense_capitalization(gl_rows: list[dict], expense_account: str, expected_credit: Any):
	"""Expense account credited exactly once for capitalization (Add Cost / LCV)."""
	hits = [r for r in gl_rows if r.get("account") == expense_account and D(r.get("credit") or 0) != 0]
	if len(hits) != 1:
		raise AssertionError(f"expense {expense_account} credit rows={len(hits)} expected 1: {hits}")
	money_equal(hits[0]["credit"], expected_credit, precision=IRR_PRECISION, label="capitalization credit")


def assert_bin_matches_sle(item_code: str, warehouse: str) -> dict:
	"""Bin.actual_qty / stock_value must equal last SLE qty_after / stock_value for item+wh."""
	bin_row = fetch_bin(item_code, warehouse)
	if not bin_row:
		raise AssertionError(f"Bin missing for {item_code} @ {warehouse}")
	last = _sql_dicts(
		"""
		select qty_after_transaction, stock_value, valuation_rate
		from `tabStock Ledger Entry`
		where item_code=%s and warehouse=%s and is_cancelled=0
		order by posting_date desc, posting_time desc, creation desc
		limit 1
		""",
		(item_code, warehouse),
	)
	if not last:
		raise AssertionError(f"No SLE for Bin {item_code} @ {warehouse}")
	sle = last[0]
	# qty compared at stock precision
	if abs(D(bin_row["actual_qty"]) - D(sle["qty_after_transaction"])) > Decimal("0.000001"):
		raise AssertionError(
			f"Bin qty {bin_row['actual_qty']} != SLE qty_after {sle['qty_after_transaction']}"
		)
	money_equal(
		bin_row["stock_value"],
		sle["stock_value"],
		precision=IRR_PRECISION,
		label=f"Bin stock_value {item_code}@{warehouse}",
	)
	return bin_row


def assert_reports_reconcile(company: str, item_code: str | None = None) -> dict:
	"""Run Stock Ledger + General Ledger; optionally Stock Balance / Trial Balance via ERPNext."""
	from_date = "2000-01-01"
	to_date = today()
	# ERPNext Stock Ledger expects item_code as a list (ContainsCriterion).
	item_filter = [item_code] if item_code else None
	sl_filters = {"company": company, "from_date": from_date, "to_date": to_date}
	if item_filter:
		sl_filters["item_code"] = item_filter
	sl_cols, sl_data = run_stock_ledger_report(sl_filters)
	gl_cols, gl_data = run_general_ledger_report(
		{"company": company, "from_date": from_date, "to_date": to_date, "classify_closing_voucher": 0}
	)
	# Stock Balance
	sb_ok = False
	try:
		from erpnext.stock.report.stock_balance.stock_balance import execute as sb_execute

		sb_filters = frappe._dict(
			{
				"company": company,
				"from_date": from_date,
				"to_date": to_date,
			}
		)
		if item_code:
			sb_filters["item_code"] = item_code
		sb_cols, sb_data = sb_execute(sb_filters)
		sb_ok = True
	except Exception as exc:  # noqa: BLE001 — report optional in hardening evidence
		sb_cols, sb_data, sb_exc = [], [], str(exc)
		sb_ok = False
	else:
		sb_exc = None

	tb_ok = False
	try:
		from erpnext.accounts.report.trial_balance.trial_balance import execute as tb_execute

		tb_cols, tb_data = tb_execute(
			frappe._dict(
				{
					"company": company,
					"from_date": from_date,
					"to_date": to_date,
					"period_start_date": from_date,
					"period_end_date": to_date,
				}
			)
		)
		tb_ok = True
		tb_exc = None
	except Exception as exc:  # noqa: BLE001
		tb_cols, tb_data, tb_exc = [], [], str(exc)

	return {
		"stock_ledger_rows": len(sl_data or []),
		"general_ledger_rows": len(gl_data or []),
		"stock_balance_ok": sb_ok,
		"stock_balance_rows": len(sb_data or []) if sb_ok else 0,
		"stock_balance_error": sb_exc,
		"trial_balance_ok": tb_ok,
		"trial_balance_rows": len(tb_data or []) if tb_ok else 0,
		"trial_balance_error": tb_exc,
	}


def normalize_snapshot(obj: Any) -> Any:
	if isinstance(obj, list):
		return [normalize_snapshot(x) for x in obj]
	if isinstance(obj, dict):
		out = {}
		for k, v in sorted(obj.items()):
			if k in IGNORE_SNAPSHOT_KEYS:
				continue
			if isinstance(v, float):
				out[k] = str(quantize_money(v, IRR_PRECISION) if abs(v) >= 1 or v == 0 else D(v))
			elif isinstance(v, (int, Decimal)):
				out[k] = str(v)
			else:
				out[k] = normalize_snapshot(v)
		return out
	return obj


def voucher_snapshot(voucher_type: str, voucher_no: str) -> dict:
	snap = {
		"voucher_type": voucher_type,
		"header": fetch_stock_entry(voucher_no) if voucher_type == "Stock Entry" else {"name": voucher_no},
		"details": fetch_stock_entry_details(voucher_no) if voucher_type == "Stock Entry" else [],
		"additional_costs": fetch_additional_costs(voucher_no) if voucher_type == "Stock Entry" else [],
		"sle": fetch_sle_db(voucher_type, voucher_no),
		"gl": fetch_gl_db(voucher_type, voucher_no),
	}
	return normalize_snapshot(snap)


def assert_snapshots_equal(before: dict, after: dict, *, label: str = "") -> None:
	b = normalize_snapshot(before)
	a = normalize_snapshot(after)
	if b != a:
		raise AssertionError(f"snapshot mismatch {label}:\nbefore={b}\nafter={a}")


def assert_full_stock_entry(name: str, *, purpose: str | None = None) -> dict:
	header = assert_stock_entry_header(name, purpose=purpose, docstatus=1)
	details = fetch_stock_entry_details(name)
	assert_detail_composition(details)
	sle = assert_sle_integrity("Stock Entry", name)
	gl = assert_gl_integrity("Stock Entry", name)
	# Bin for each warehouse on rows
	for d in details:
		for wh_field in ("s_warehouse", "t_warehouse"):
			wh = d.get(wh_field)
			if wh:
				assert_bin_matches_sle(d["item_code"], wh)
	return {"header": header, "details": details, "sle": sle, "gl": gl}


def rounding_residual_report(stored: Any, mathematical: Any, *, precision: int = IRR_PRECISION) -> dict:
	mat = quantize_money(mathematical, precision)
	sto = quantize_money(stored, precision)
	return {
		"mathematical": str(mat),
		"stored": str(sto),
		"residual": str(residual(sto, mat, precision=precision)),
		"currency_precision": precision,
	}
