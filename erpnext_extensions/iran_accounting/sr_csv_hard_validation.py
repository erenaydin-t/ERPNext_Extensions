# Copyright (c) 2026, ERPNext Extensions contributors
"""CSV + ERPNext hard validation for Stock Reconciliation difference_amount."""

from __future__ import annotations

import csv
import os
import re
from typing import Any

import frappe
from frappe.utils import flt

from erpnext_extensions.iran_accounting.domain.currency import (
	get_company_currency,
	round_row_amount_financial,
)
from erpnext_extensions.iran_accounting.domain.qty_rate_amount import (
	override_difference_amount,
	sum_stock_reconciliation_amount_difference,
	sum_stock_reconciliation_row_amounts,
)
from erpnext_extensions.iran_accounting.qty_rate_consistency import (
	_gl_stock_totals,
	_sle_value_diff_sum,
	check_qty_rate_amount_consistency,
)

DEFAULT_VOUCHERS = (
	"MAT-RECO-2026-00187",
	"MAT-RECO-2026-00245",
	"MAT-RECO-2026-00248",
	"MAT-RECO-2026-00197",
)

_CSV_QTY_ALIASES = ("quantity", "qty")
_CSV_RATE_ALIASES = ("valuation rate", "valuation_rate", "rate")
_CSV_CURRENT_AMOUNT_ALIASES = ("current amount", "current_amount")
_CSV_AMOUNT_ALIASES = ("amount",)
_CSV_AMOUNT_DIFF_ALIASES = ("amount difference", "amount_difference")


def _norm_header(h: str) -> str:
	return re.sub(r"\s+", " ", (h or "").strip().lower())


def _pick(row: dict, aliases: tuple[str, ...]):
	for a in aliases:
		for k, v in row.items():
			if _norm_header(k) == a:
				return v
	return None


def _parse_num(value) -> float:
	if value in (None, ""):
		return 0.0
	if isinstance(value, (int, float)):
		return float(value)
	text = str(value).strip().replace(",", "")
	if not text:
		return 0.0
	return float(text)


def _irr_integer(value, currency: str) -> bool:
	if (currency or "").upper() != "IRR":
		return True
	return flt(value) == int(flt(value))


def load_csv_rows(csv_path: str) -> tuple[list[dict], str]:
	"""Return cleaned data rows and detected currency (default IRR)."""
	if not os.path.isfile(csv_path):
		frappe.throw(f"CSV not found: {csv_path}")

	rows: list[dict] = []
	with open(csv_path, newline="", encoding="utf-8-sig") as f:
		reader = csv.DictReader(f)
		if not reader.fieldnames:
			frappe.throw("CSV has no header row")
		for raw in reader:
			qty = _pick(raw, _CSV_QTY_ALIASES)
			rate = _pick(raw, _CSV_RATE_ALIASES)
			if qty in (None, "") and rate in (None, ""):
				continue
			if _norm_header(str(qty or "")) in ("quantity", "qty"):
				continue
			rows.append(raw)
	return rows, "IRR"


def compute_csv_expected(rows: list[dict], currency: str = "IRR") -> dict:
	"""Recompute per-row amounts and header from CSV columns."""
	line_details = []
	sum_amount_difference = 0.0
	sum_amount = 0.0
	row_failures: list[str] = []

	for i, raw in enumerate(rows, start=1):
		qty = _parse_num(_pick(raw, _CSV_QTY_ALIASES))
		rate = _parse_num(_pick(raw, _CSV_RATE_ALIASES))
		current_amount = _parse_num(_pick(raw, _CSV_CURRENT_AMOUNT_ALIASES))
		csv_amount = _pick(raw, _CSV_AMOUNT_ALIASES)
		csv_amount_diff = _pick(raw, _CSV_AMOUNT_DIFF_ALIASES)

		expected_amount = float(round_row_amount_financial(qty, rate, currency))
		expected_amount_difference = expected_amount - current_amount

		if not _irr_integer(expected_amount, currency):
			row_failures.append(f"row {i}: non-integer IRR amount {expected_amount}")
		if not _irr_integer(expected_amount_difference, currency):
			row_failures.append(f"row {i}: non-integer IRR amount_difference {expected_amount_difference}")

		if csv_amount not in (None, ""):
			if flt(_parse_num(csv_amount)) != expected_amount:
				row_failures.append(f"row {i}: CSV Amount {csv_amount} != recomputed {expected_amount}")
		if csv_amount_diff not in (None, ""):
			if flt(_parse_num(csv_amount_diff)) != expected_amount_difference:
				row_failures.append(
					f"row {i}: CSV Amount Difference {csv_amount_diff} != recomputed {expected_amount_difference}"
				)

		sum_amount_difference += expected_amount_difference
		sum_amount += expected_amount
		line_details.append(
			{
				"row": i,
				"qty": qty,
				"rate": rate,
				"expected_amount": expected_amount,
				"current_amount": current_amount,
				"expected_amount_difference": expected_amount_difference,
			}
		)

	return {
		"currency": currency,
		"row_count": len(rows),
		"csv_expected_header": flt(sum_amount_difference),
		"csv_sum_amount_gross": flt(sum_amount),
		"row_failures": row_failures,
		"lines": line_details,
	}


def validate_erpnext_voucher(
	voucher_no: str,
	csv_expected_header: float | None = None,
	*,
	currency: str = "IRR",
) -> dict:
	from erpnext_extensions.iran_accounting.integration.bootstrap import apply

	apply()

	if not frappe.db.exists("Stock Reconciliation", voucher_no):
		return {"voucher_no": voucher_no, "status": "SKIP", "reason": "not found"}

	doc = frappe.get_doc("Stock Reconciliation", voucher_no)
	ccy = get_company_currency(doc.company) or currency
	erp_header = flt(frappe.db.get_value("Stock Reconciliation", voucher_no, "difference_amount"))
	db_recomputed = flt(
		frappe.db.sql(
			"""
			select coalesce(sum(amount_difference), 0)
			from `tabStock Reconciliation Item`
			where parent=%s
			""",
			voucher_no,
		)[0][0]
	)
	override_difference_amount(doc)
	override_header = flt(doc.difference_amount)
	gross_sum = sum_stock_reconciliation_row_amounts(doc)
	net_sum = sum_stock_reconciliation_amount_difference(doc)

	gl = _gl_stock_totals("Stock Reconciliation", voucher_no)
	gl_mag = max(flt(gl.get("debit")), flt(gl.get("credit")))
	sle_total = flt(_sle_value_diff_sum("Stock Reconciliation", voucher_no)) if doc.docstatus == 1 else None

	chk = (
		check_qty_rate_amount_consistency("Stock Reconciliation", voucher_no, doc.company)
		if doc.docstatus == 1
		else None
	)

	delta_csv_vs_erp = None if csv_expected_header is None else flt(csv_expected_header) - erp_header
	delta_db_vs_erp = db_recomputed - erp_header

	log_block = {
		"CSV_EXPECTED_HEADER": csv_expected_header,
		"DB_RECOMPUTED_HEADER": db_recomputed,
		"ERP_HEADER": erp_header,
		"OVERRIDE_HEADER": override_header,
		"DELTA_CSV_VS_ERP": delta_csv_vs_erp,
		"DELTA_DB_VS_ERP": delta_db_vs_erp,
		"SUM_AMOUNT_GROSS": gross_sum,
		"SUM_AMOUNT_DIFFERENCE": net_sum,
		"GL_MAGNITUDE": gl_mag if doc.docstatus == 1 else None,
		"SLE_TOTAL": sle_total,
	}

	failures: list[str] = []
	if erp_header != db_recomputed:
		failures.append("header-level: ERP_HEADER != DB_RECOMPUTED_HEADER (Σ amount_difference)")
	if erp_header != net_sum:
		failures.append("header-level: ERP_HEADER != Σ normalized amount_difference")
	if csv_expected_header is not None and erp_header != flt(csv_expected_header):
		failures.append("header-level: ERP_HEADER != CSV_EXPECTED_HEADER")
	if erp_header == gross_sum and gross_sum != net_sum:
		failures.append("header-level: difference_amount == SUM(amount) gross mode")
	if doc.docstatus == 1:
		if sle_total is not None and abs(erp_header) != abs(sle_total):
			failures.append(f"SLE-level: |ERP_HEADER| {erp_header} != |SLE| {sle_total}")
		if gl_mag and abs(erp_header) != gl_mag:
			failures.append(f"GL-level: |ERP_HEADER| {erp_header} != GL magnitude {gl_mag}")
		if chk and chk.get("status") != "PASS":
			failures.extend([f"consistency: {x}" for x in chk.get("consistency_failures") or []])

	for item in doc.items:
		exp_amt = float(round_row_amount_financial(item.qty, item.valuation_rate, ccy))
		if not _irr_integer(item.amount, ccy):
			failures.append(f"row-level: {item.name} fractional IRR amount {item.amount}")
		if flt(item.amount) != exp_amt:
			failures.append(f"row-level: {item.name} amount {item.amount} != round(qty×rate) {exp_amt}")
		exp_diff = flt(item.amount) - flt(item.current_amount)
		if flt(item.amount_difference) != exp_diff:
			failures.append(
				f"row-level: {item.name} amount_difference {item.amount_difference} != {exp_diff}"
			)

	status = "PASS" if not failures else "FAIL"
	print(f"\n=== {voucher_no} ===")
	for k, v in log_block.items():
		print(f"{k}: {v}")
	if failures:
		print("FAILURES:")
		for f in failures:
			print(f"  - {f}")

	return {
		"voucher_no": voucher_no,
		"status": status,
		"log": log_block,
		"failures": failures,
		"consistency": chk,
	}


def run_hard_validation(
	csv_path: str | None = None,
	voucher_nos: list[str] | None = None,
	*,
	csv_voucher_map: dict[str, str] | None = None,
) -> dict[str, Any]:
	"""
	csv_voucher_map: optional {voucher_no: csv_path} when each doc has its own export.
	If csv_path is set, CSV header is compared to every voucher (same export).
	"""
	voucher_nos = list(voucher_nos or DEFAULT_VOUCHERS)
	csv_expected_header = None
	csv_block = None
	overall_failures: list[str] = []

	if csv_path:
		raw_rows, currency = load_csv_rows(csv_path)
		csv_block = compute_csv_expected(raw_rows, currency)
		csv_expected_header = csv_block["csv_expected_header"]
		if csv_block["row_failures"]:
			overall_failures.extend([f"csv: {x}" for x in csv_block["row_failures"]])
		print(
			f"\nCSV_EXPECTED_HEADER: {csv_expected_header} "
			f"(rows={csv_block['row_count']}, gross={csv_block['csv_sum_amount_gross']})"
		)

	results = []
	for voucher_no in voucher_nos:
		path = (csv_voucher_map or {}).get(voucher_no) or csv_path
		exp = None
		if path and path != csv_path:
			raw_rows, currency = load_csv_rows(path)
			exp = compute_csv_expected(raw_rows, currency)["csv_expected_header"]
		elif csv_expected_header is not None:
			exp = csv_expected_header
		results.append(validate_erpnext_voucher(voucher_no, exp))
		if results[-1]["status"] == "FAIL":
			overall_failures.extend(results[-1]["failures"])

	overall = "PASS" if not overall_failures else "FAIL"
	print(f"\n>>> OVERALL: {overall}")
	return {
		"overall": overall,
		"csv": csv_block,
		"vouchers": results,
		"failures": overall_failures,
	}


@frappe.whitelist()
def run_hard_validation_api(csv_path: str | None = None, voucher_nos: str | None = None):
	names = [x.strip() for x in (voucher_nos or "").split(",") if x.strip()] or None
	return run_hard_validation(csv_path=csv_path, voucher_nos=names)
