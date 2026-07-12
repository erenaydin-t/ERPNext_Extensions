# Copyright (c) 2026, ERPNext Extensions contributors
"""Diagnostics: qty × rate vs stored amounts; document vs GL vs SLE totals."""

from __future__ import annotations

from typing import Any

import frappe
from frappe.utils import flt

from erpnext_extensions.iran_accounting.qty_rate_amount import row_qty_rate_check
from erpnext_extensions.iran_accounting.rounding import get_company_currency, is_irr_company, round_currency


def _gl_stock_totals(voucher_type: str, voucher_no: str) -> dict:
	rows = frappe.db.sql(
		"""
		select sum(debit) as debit, sum(credit) as credit
		from `tabGL Entry`
		where voucher_type=%s and voucher_no=%s and is_cancelled=0
		""",
		(voucher_type, voucher_no),
		as_dict=True,
	)
	row = rows[0] if rows else {}
	return {"debit": flt(row.get("debit")), "credit": flt(row.get("credit"))}


def _sle_value_diff_sum(voucher_type: str, voucher_no: str) -> float:
	return flt(
		frappe.db.sql(
			"""
			select coalesce(sum(stock_value_difference), 0)
			from `tabStock Ledger Entry`
			where voucher_type=%s and voucher_no=%s and is_cancelled=0
			""",
			(voucher_type, voucher_no),
		)[0][0]
	)


def _item_rows_stock_reconciliation(doc) -> list[dict]:
	company = doc.company
	ccy = get_company_currency(company)
	rows = []
	for item in doc.get("items") or []:
		for label, qty, rate, stored in (
			("amount", item.qty, item.valuation_rate, item.amount),
			("current_amount", item.current_qty, item.current_valuation_rate, item.current_amount),
		):
			if qty in (None, "") or rate in (None, ""):
				continue
			rows.append(
				{
					"row_name": item.name,
					"item_code": item.item_code,
					**row_qty_rate_check(qty, rate, stored, ccy, label=label),
				}
			)
		if item.amount_difference is not None:
			exp = round_currency(flt(item.amount) - flt(item.current_amount), ccy)
			rows.append(
				{
					"row_name": item.name,
					"item_code": item.item_code,
					"field": "amount_difference",
					"expected_rounded_amount": exp,
					"stored_amount": flt(item.amount_difference),
					"residual": flt(item.amount_difference) - exp,
					"status": "PASS" if flt(item.amount_difference) == exp else "FAIL",
				}
			)
	return rows


def _item_rows_generic(doc, child_table: str, qty_field: str = "qty") -> list[dict]:
	ccy = get_company_currency(doc.company)
	tx = getattr(doc, "currency", None) or ccy
	rows = []
	for item in doc.get(child_table) or []:
		qty = item.get(qty_field)
		if item.get("rate") is not None and item.get("amount") is not None:
			rows.append(
				{
					"row_name": item.name,
					"item_code": item.get("item_code"),
					**row_qty_rate_check(qty, item.rate, item.amount, tx, label="amount"),
				}
			)
		if item.get("base_rate") is not None and item.get("base_amount") is not None:
			rows.append(
				{
					"row_name": item.name,
					"item_code": item.get("item_code"),
					**row_qty_rate_check(qty, item.base_rate, item.base_amount, ccy, label="base_amount"),
				}
			)
		if item.get("net_rate") is not None and item.get("net_amount") is not None:
			rows.append(
				{
					"row_name": item.name,
					"item_code": item.get("item_code"),
					**row_qty_rate_check(qty, item.net_rate, item.net_amount, tx, label="net_amount"),
				}
			)
	return rows


def _item_rows_stock_entry(doc) -> list[dict]:
	ccy = get_company_currency(doc.company)
	rows = []
	for item in doc.get("items") or []:
		qty = item.qty
		if item.get("basic_rate") is not None and item.get("basic_amount") is not None:
			rows.append(
				{
					"row_name": item.name,
					"item_code": item.item_code,
					**row_qty_rate_check(qty, item.basic_rate, item.basic_amount, ccy, label="basic_amount"),
				}
			)
		if item.get("amount") is not None:
			rate = item.basic_rate if item.get("basic_rate") is not None else item.valuation_rate
			if rate is not None:
				rows.append(
					{
						"row_name": item.name,
						"item_code": item.item_code,
						**row_qty_rate_check(qty, rate, item.amount, ccy, label="amount"),
					}
				)
	return rows


def check_qty_rate_amount_consistency(
	doctype: str,
	voucher_no: str,
	company: str | None = None,
) -> dict[str, Any]:
	"""Compare row qty×rate amounts, header totals, GL, and SLE (if applicable)."""
	if not frappe.db.exists(doctype, voucher_no):
		frappe.throw(f"{doctype} {voucher_no} not found")
	doc = frappe.get_doc(doctype, voucher_no)
	company = company or doc.company
	ccy = get_company_currency(company)

	if doctype == "Stock Reconciliation":
		item_rows = _item_rows_stock_reconciliation(doc)
	elif doctype == "Stock Entry":
		item_rows = _item_rows_stock_entry(doc)
	elif doctype in ("Purchase Order", "Purchase Invoice", "Sales Invoice"):
		item_rows = _item_rows_generic(doc, "items")
	elif doctype in ("Purchase Receipt", "Delivery Note"):
		item_rows = _item_rows_generic(doc, "items")
	else:
		frappe.throw(f"Unsupported doctype: {doctype}")

	row_fail = [r for r in item_rows if r.get("status") == "FAIL"]
	totals: dict[str, Any] = {"company_currency": ccy}

	if doctype == "Stock Reconciliation":
		sum_amount = sum(flt(i.amount) for i in doc.get("items") or [])
		sum_diff = sum(flt(i.amount_difference) for i in doc.get("items") or [])
		header = flt(doc.difference_amount)
		totals["sum_row_amount"] = sum_amount
		totals["sum_amount_difference"] = sum_diff
		totals["difference_amount"] = header
		totals["purpose"] = doc.get("purpose")
		totals["header_vs_rows_residual"] = header - sum_diff
		totals["header_vs_amount_difference_residual"] = header - sum_diff
		totals["header_vs_gross_amount_residual"] = header - sum_amount
		gl = _gl_stock_totals(doctype, voucher_no)
		totals["gl_debit"] = gl["debit"]
		totals["gl_credit"] = gl["credit"]
		totals["gl_net"] = gl["debit"] - gl["credit"]
		sle_sum = _sle_value_diff_sum(doctype, voucher_no)
		totals["sle_stock_value_difference_sum"] = sle_sum
		totals["difference_vs_sle_residual"] = round_currency(header - sle_sum, ccy)
		gl_mag = max(gl["debit"], gl["credit"])
		totals["gl_magnitude"] = gl_mag
		totals["difference_vs_gl_residual"] = round_currency(abs(header) - gl_mag, ccy)

	item_amount_sum = sum(
		r.get("stored_amount") or 0
		for r in item_rows
		if r.get("field") == "amount" and r.get("stored_amount") is not None
	)
	totals["sum_row_amount_fields"] = item_amount_sum

	consistency_fail = []
	if doctype == "Stock Reconciliation" and is_irr_company(company):
		if flt(totals.get("header_vs_rows_residual")):
			consistency_fail.append("difference_amount != sum(amount_difference)")
		if abs(flt(totals.get("difference_vs_gl_residual"))) > 0:
			consistency_fail.append("difference_amount vs GL magnitude")
		if abs(flt(totals.get("difference_vs_sle_residual"))) > 0:
			consistency_fail.append(
				f"difference_amount vs SLE sum residual={totals.get('difference_vs_sle_residual')}"
			)

	status = "PASS" if not row_fail and not consistency_fail else "FAIL"
	out = {
		"doctype": doctype,
		"voucher_no": voucher_no,
		"company": company,
		"status": status,
		"item_rows": item_rows,
		"totals": totals,
		"consistency_failures": consistency_fail,
		"row_fail_count": len(row_fail),
	}
	print(out)
	return out
