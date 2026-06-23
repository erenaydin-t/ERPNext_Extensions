# Copyright (c) 2026, ERPNext Extensions contributors
"""Validation for foreign-currency buying/selling on IRR companies."""

from __future__ import annotations

import json
from typing import Any

import frappe
from frappe.utils import flt

from erpnext_extensions.iran_accounting.reports import (
	run_general_ledger_report,
	run_stock_ledger_report,
	stock_ledger_report_monetary_fields,
)
from erpnext_extensions.iran_accounting.rounding import (
	amount_is_fractional,
	get_company_currency,
	is_irr_company,
	is_irr_currency,
)
from erpnext_extensions.iran_accounting.sql_validation import (
	sql_find_fractional_irr_gl,
	sql_find_fractional_irr_sle,
	sql_get_gl_rows,
	sql_get_sle_rows,
)
from erpnext_extensions.iran_accounting.stock_ledger_report import (
	default_stock_ledger_filters,
	export_stock_ledger_xlsx_rows,
	fractional_cells_in_report_rows,
	fractional_monetary_in_xlsx,
)
from erpnext_extensions.iran_accounting.validation import assert_report_rows_no_irr_decimals

ZERO_DECIMAL_FOREIGN = frozenset({"USD", "EUR"})

PI_IRR_TOTAL_FIELDS = (
	"base_grand_total",
	"base_net_total",
	"base_total",
	"base_total_taxes_and_charges",
	"base_rounded_total",
)

PI_TXN_TOTAL_FIELDS = ("grand_total", "net_total", "total", "total_taxes_and_charges")

SI_IRR_TOTAL_FIELDS = PI_IRR_TOTAL_FIELDS
SI_TXN_TOTAL_FIELDS = PI_TXN_TOTAL_FIELDS


def _account_currency(account: str | None) -> str | None:
	if not account:
		return None
	return frappe.get_cached_value("Account", account, "account_currency")


def gl_foreign_currency_violations(gl_rows: list[dict], company: str) -> list[dict]:
	"""IRR company-currency GL must be integer; IRR account-currency fields integer; foreign may be decimal."""
	if not is_irr_company(company):
		return []
	company_currency = get_company_currency(company)
	violations = []
	for row in gl_rows:
		for field in ("debit", "credit"):
			val = row.get(field)
			if val not in (None, "") and amount_is_fractional(val, company_currency):
				violations.append({"rule": "irr_company_gl", "field": field, "value": val, "gle": row.get("name")})
		for field in ("debit_in_account_currency", "credit_in_account_currency"):
			val = row.get(field)
			if val in (None, ""):
				continue
			acct_cur = row.get("account_currency") or _account_currency(row.get("account"))
			if is_irr_currency(acct_cur) and amount_is_fractional(val, acct_cur):
				violations.append(
					{"rule": "irr_account_currency_gl", "field": field, "value": val, "gle": row.get("name")}
				)
	return violations


def foreign_decimal_gl_samples(gl_rows: list[dict], txn_currency: str) -> list[dict]:
	"""Rows where txn currency account fields show decimals (expected allowed)."""
	out = []
	for row in gl_rows:
		acct_cur = row.get("account_currency") or _account_currency(row.get("account"))
		if acct_cur != txn_currency:
			continue
		for field in ("debit_in_account_currency", "credit_in_account_currency"):
			val = flt(row.get(field))
			if val and abs(val - round(val)) > 1e-9:
				out.append({"field": field, "value": val, "account": row.get("account"), "gle": row.get("name")})
	return out


def document_totals_violations(doctype: str, voucher_no: str, company: str, txn_currency: str) -> list[dict]:
	if not is_irr_company(company):
		return []
	doc = frappe.get_doc(doctype, voucher_no)
	irr_cur = get_company_currency(company)
	out = []
	if doctype == "Purchase Invoice":
		irr_fields, txn_fields = PI_IRR_TOTAL_FIELDS, PI_TXN_TOTAL_FIELDS
	elif doctype == "Sales Invoice":
		irr_fields, txn_fields = SI_IRR_TOTAL_FIELDS, SI_TXN_TOTAL_FIELDS
	else:
		irr_fields, txn_fields = (), ()

	for field in irr_fields:
		val = doc.get(field)
		if val not in (None, "") and amount_is_fractional(val, irr_cur):
			out.append({"rule": "irr_base_total", "field": field, "value": val})

	doc_cur = doc.get("currency") or irr_cur
	if doc_cur == txn_currency:
		for field in txn_fields:
			val = doc.get(field)
			if val in (None, ""):
				continue
			if doc_cur in ZERO_DECIMAL_FOREIGN and abs(flt(val) - round(flt(val))) > 1e-9:
				pass  # allowed
	return out


def report_export_ok_for_voucher(company: str, voucher_no: str, posting_date: str) -> dict:
	filters = default_stock_ledger_filters(company, voucher_no=voucher_no, from_date=posting_date, to_date=posting_date)
	gl_filters = {"company": company, "from_date": posting_date, "to_date": posting_date, "voucher_no": voucher_no}
	try:
		_, gl_data = run_general_ledger_report(gl_filters)
		assert_report_rows_no_irr_decimals(gl_data, company, ("debit", "credit", "balance"))
		gl_ok = True
	except Exception as exc:
		gl_ok = False
		gl_err = str(exc)
	else:
		gl_err = ""

	try:
		sl_columns, sl_data = run_stock_ledger_report(filters)
		sl_fields = tuple(stock_ledger_report_monetary_fields(sl_columns, filters))
		assert_report_rows_no_irr_decimals(sl_data, company, sl_fields)
		sl_ok = True
		sl_frac = []
	except Exception as exc:
		sl_ok = False
		sl_err = str(exc)
		sl_frac = []
	else:
		sl_err = ""
		sl_frac = fractional_cells_in_report_rows(sl_data, company, sl_fields)

	try:
		exp_cols, xlsx_rows = export_stock_ledger_xlsx_rows(filters)
		exp_frac = fractional_monetary_in_xlsx(exp_cols, xlsx_rows, company)
		export_ok = not exp_frac
	except Exception as exc:
		export_ok = False
		exp_frac = [{"error": str(exc)}]

	return {
		"gl_report_ok": gl_ok,
		"gl_report_error": gl_err,
		"sl_report_ok": sl_ok,
		"sl_report_error": sl_err,
		"sl_report_fractional": sl_frac[:5],
		"export_ok": export_ok,
		"export_fractional": exp_frac[:5],
	}


def validate_foreign_currency_voucher(
	doctype: str,
	voucher_no: str,
	company: str,
	txn_currency: str,
	*,
	expect_sle: bool = True,
) -> dict[str, Any]:
	"""Full DB + report/export validation for a foreign-currency stock voucher."""
	gl_rows = sql_get_gl_rows(doctype, voucher_no)
	sle_rows = sql_get_sle_rows(doctype, voucher_no) if expect_sle else []

	gl_viol = gl_foreign_currency_violations(gl_rows, company)
	frac_gl = sql_find_fractional_irr_gl(doctype, voucher_no, company)
	frac_sle = sql_find_fractional_irr_sle(doctype, voucher_no, company) if expect_sle else []
	doc_viol = document_totals_violations(doctype, voucher_no, company, txn_currency)

	posting = frappe.db.get_value(doctype, voucher_no, "posting_date")
	reports = report_export_ok_for_voucher(company, voucher_no, str(posting)) if posting else {}

	fx_decimals = foreign_decimal_gl_samples(gl_rows, txn_currency)

	ok = (
		not gl_viol
		and not frac_gl
		and not frac_sle
		and not doc_viol
		and reports.get("gl_report_ok", True)
		and reports.get("sl_report_ok", True)
		and reports.get("export_ok", True)
	)

	return {
		"status": "PASS" if ok else "FAIL",
		"ok": ok,
		"gl_violations": gl_viol,
		"fractional_irr_gl": frac_gl,
		"fractional_irr_sle": frac_sle,
		"doc_total_violations": doc_viol,
		"foreign_decimal_samples": fx_decimals[:5],
		"gl_sql_sample": gl_rows[:4],
		"sle_sql_sample": sle_rows[:4],
		"reports": reports,
	}


def compact_evidence(check: dict) -> str:
	payload = {
		"status": check.get("status"),
		"gl_viol": len(check.get("gl_violations") or []),
		"frac_gl": len(check.get("fractional_irr_gl") or []),
		"frac_sle": len(check.get("fractional_irr_sle") or []),
		"fx_decimal_samples": check.get("foreign_decimal_samples"),
		"gl_sample": check.get("gl_sql_sample"),
		"sle_sample": check.get("sle_sql_sample"),
		"reports": check.get("reports"),
	}
	return json.dumps(payload, default=str)[:500]
