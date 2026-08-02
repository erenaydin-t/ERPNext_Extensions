# Copyright (c) 2026, ERPNext Extensions contributors

from __future__ import annotations

import re
from typing import Any

import frappe
from frappe.utils import flt

from erpnext_extensions.iran_accounting.rounding import (
	GL_AMOUNT_FIELDS,
	SLE_MONETARY_FIELDS,
	amount_is_fractional,
	get_company_currency,
	is_irr_company,
	is_irr_currency,
	round_currency,
)

GL_ROW_FIELDS = [
	"name",
	"account",
	"account_currency",
	"transaction_currency",
	"debit",
	"credit",
	"debit_in_account_currency",
	"credit_in_account_currency",
	"debit_in_transaction_currency",
	"credit_in_transaction_currency",
	"debit_in_reporting_currency",
	"credit_in_reporting_currency",
	"remarks",
	"cost_center",
]

SLE_ROW_FIELDS = [
	"name",
	"stock_value",
	"stock_value_difference",
	"valuation_rate",
	"incoming_rate",
	"outgoing_rate",
	"actual_qty",
	"qty_after_transaction",
]


def currency_for_gl_field(row: dict, field: str, company_currency: str) -> str:
	if field in ("debit", "credit"):
		return company_currency
	if field in ("debit_in_account_currency", "credit_in_account_currency"):
		return row.get("account_currency") or company_currency
	if field in ("debit_in_transaction_currency", "credit_in_transaction_currency"):
		return row.get("transaction_currency") or company_currency
	if field in ("debit_in_reporting_currency", "credit_in_reporting_currency"):
		reporting = frappe.get_cached_value("Company", row.get("company"), "reporting_currency")
		return reporting or company_currency
	return company_currency


def fractional_gl_fields(row: dict, company: str) -> list[dict]:
	if not is_irr_company(company):
		return []
	company_currency = get_company_currency(company)
	row = dict(row)
	row.setdefault("company", company)
	out = []
	for field in GL_AMOUNT_FIELDS:
		val = row.get(field)
		if val in (None, ""):
			continue
		cur = currency_for_gl_field(row, field, company_currency)
		if is_irr_currency(cur) and amount_is_fractional(val, cur):
			out.append({"field": field, "value": val, "currency": cur, "gle": row.get("name")})
	return out


def fractional_sle_fields(row: dict, company: str) -> list[dict]:
	if not is_irr_company(company):
		return []
	company_currency = get_company_currency(company)
	out = []
	for field in SLE_MONETARY_FIELDS:
		val = row.get(field)
		if val in (None, ""):
			continue
		if amount_is_fractional(val, company_currency):
			out.append({"field": field, "value": val, "sle": row.get("name")})
	return out


def fetch_gl_rows(voucher_type: str, voucher_no: str) -> list[dict]:
	return frappe.get_all(
		"GL Entry",
		filters={"voucher_type": voucher_type, "voucher_no": voucher_no, "is_cancelled": 0},
		fields=GL_ROW_FIELDS,
		order_by="creation asc",
	)


def fetch_sle_rows(voucher_type: str, voucher_no: str) -> list[dict]:
	return frappe.get_all(
		"Stock Ledger Entry",
		filters={"voucher_type": voucher_type, "voucher_no": voucher_no, "is_cancelled": 0},
		fields=SLE_ROW_FIELDS,
		order_by="creation asc",
	)


def stock_adj_round_off_rows(gl_rows: list[dict], company: str) -> list[dict]:
	stock_adj = frappe.get_cached_value("Company", company, "stock_adjustment_account")
	round_off = frappe.get_cached_value("Company", company, "round_off_account")
	out = []
	for row in gl_rows:
		account = row.get("account")
		if not account:
			continue
		if account in (stock_adj, round_off):
			out.append(row)
			continue
		account_type = frappe.get_cached_value("Account", account, "account_type")
		if account_type in ("Stock Adjustment", "Round Off"):
			out.append(row)
	return out


def gl_debit_credit_totals(gl_rows: list[dict]) -> tuple[float, float]:
	return sum(flt(r.get("debit")) for r in gl_rows), sum(flt(r.get("credit")) for r in gl_rows)


def is_doubled_gl(debit_total: float, expected: float) -> bool:
	if not expected:
		return False
	return flt(debit_total) >= 2 * flt(expected) - 0.01


def assert_no_fractional_irr_in_numeric(value: Any, currency: str | None = None) -> None:
	if value in (None, ""):
		return
	if currency and not is_irr_currency(currency):
		return
	if amount_is_fractional(value, currency or "IRR"):
		raise AssertionError(f"Fractional IRR value: {value} ({currency or 'IRR'})")


def assert_report_rows_no_irr_decimals(rows: list[dict], company: str, fields: tuple[str, ...]) -> None:
	if not is_irr_company(company):
		return
	currency = get_company_currency(company)
	for row in rows:
		for field in fields:
			val = row.get(field)
			if val in (None, ""):
				continue
			if isinstance(val, str) and re.search(r"\.\d", val):
				raise AssertionError(f"Report field {field} has decimal string: {val}")
			assert_no_fractional_irr_in_numeric(val, currency)


# Monetary IRR amounts in print: comma-grouped or large integers with decimal fraction.
_IRR_MONEY_DECIMAL_RE = re.compile(
	r"(?<!\d)"  # not preceded by digit (reduce qty like 1.5 uom hits)
	r"(?:\d{1,3}(?:,\d{3})+|\d{4,})"
	r"\.\d+"
)


def find_irr_monetary_decimal_snippets(html: str) -> list[str]:
	if not html:
		return []
	return _IRR_MONEY_DECIMAL_RE.findall(html)


def check_print_html_no_irr_monetary_decimals(html: str) -> dict:
	snippets = find_irr_monetary_decimal_snippets(html)
	return {"decimal_snippets_found": snippets[:50], "status": "PASS" if not snippets else "FAIL"}


def assert_zero_value_transfer_gl_shape(stock_entry_name: str, company: str) -> dict:
	"""Zero-value transfer must not have Stock Adjustment/Round Off or doubled GL."""
	if not frappe.db.exists("Stock Entry", stock_entry_name):
		raise frappe.DoesNotExistError(stock_entry_name)
	doc = frappe.get_doc("Stock Entry", stock_entry_name)
	gl_rows = fetch_gl_rows("Stock Entry", stock_entry_name)
	debit_total, credit_total = gl_debit_credit_totals(gl_rows)
	expected_in = round_currency(doc.total_incoming_value, get_company_currency(company))
	expected_out = round_currency(doc.total_outgoing_value, get_company_currency(company))
	adj = stock_adj_round_off_rows(gl_rows, company)
	purposes = ("Material Transfer", "Material Transfer for Manufacture", "Send to Subcontractor")
	is_zero_transfer = doc.purpose in purposes and flt(doc.value_difference) == 0
	if not is_zero_transfer:
		return {"applicable": False, "ok": True}
	ok = (
		not adj
		and not is_doubled_gl(debit_total, expected_in)
		and flt(debit_total) == flt(expected_in)
		and flt(credit_total) == flt(expected_out)
	)
	return {
		"applicable": True,
		"ok": ok,
		"adj_rows": adj,
		"debit_total": debit_total,
		"credit_total": credit_total,
		"expected_in": expected_in,
		"expected_out": expected_out,
	}


def assert_no_fractional_irr_gl(voucher_type: str, voucher_no: str, company: str) -> bool:
	for row in fetch_gl_rows(voucher_type, voucher_no):
		if fractional_gl_fields(row, company):
			return False
	return True


def assert_no_fractional_irr_sle(voucher_type: str, voucher_no: str, company: str) -> bool:
	for row in fetch_sle_rows(voucher_type, voucher_no):
		if fractional_sle_fields(row, company):
			return False
	return True


def voucher_db_flags(doctype: str, voucher_no: str, company: str) -> dict:
	gl_ok = assert_no_fractional_irr_gl(doctype, voucher_no, company)
	sle_rows = fetch_sle_rows(doctype, voucher_no)
	sle_ok = True if not sle_rows else assert_no_fractional_irr_sle(doctype, voucher_no, company)
	totals_ok = True
	if doctype == "Stock Entry" and frappe.db.exists("Stock Entry", voucher_no):
		doc = frappe.get_doc("Stock Entry", voucher_no)
		cur = get_company_currency(company)
		for f in ("total_incoming_value", "total_outgoing_value", "value_difference"):
			if amount_is_fractional(doc.get(f), cur):
				totals_ok = False
	return {"gl_ok": gl_ok, "sle_ok": sle_ok, "totals_ok": totals_ok}


def summarize_voucher_check(
	doctype: str,
	voucher_no: str,
	company: str,
	gl_rows: list[dict],
	sle_rows: list[dict] | None,
	extra_checks: dict | None = None,
	print_result: dict | None = None,
	include_print: bool = False,
) -> dict:
	fractional_gl = []
	for row in gl_rows:
		fractional_gl.extend(fractional_gl_fields(row, company))

	fractional_sle = []
	if sle_rows is not None:
		for row in sle_rows:
			fractional_sle.extend(fractional_sle_fields(row, company))

	checks = {
		"no_fractional_gl": not fractional_gl,
		"no_fractional_sle": not fractional_sle,
	}
	if extra_checks:
		checks.update(extra_checks)

	if print_result and include_print:
		checks["print_no_irr_monetary_decimals"] = print_result.get("status") == "PASS"

	passed = all(checks.values()) if is_irr_company(company) else True

	return {
		"doctype": doctype,
		"voucher_no": voucher_no,
		"company": company,
		"gl_rows": gl_rows,
		"sle_rows": sle_rows or [],
		"fractional_gl_fields": fractional_gl,
		"fractional_sle_fields": fractional_sle,
		"print_check": print_result,
		"checks": checks,
		"status": "PASS" if passed else "FAIL",
	}
