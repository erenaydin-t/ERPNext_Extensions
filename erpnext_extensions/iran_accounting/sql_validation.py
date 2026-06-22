# Copyright (c) 2026, ERPNext Extensions contributors
"""Direct SQL validation for IRR monetary fields (mandatory DB checks)."""

from __future__ import annotations

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
from erpnext_extensions.iran_accounting.validation import (
	currency_for_gl_field,
	gl_debit_credit_totals,
	is_doubled_gl,
	stock_adj_round_off_rows,
)

GL_SQL_FIELDS = (
	"name",
	"account",
	"account_currency",
	"transaction_currency",
	"company",
	"debit",
	"credit",
	"debit_in_account_currency",
	"credit_in_account_currency",
	"debit_in_transaction_currency",
	"credit_in_transaction_currency",
	"debit_in_reporting_currency",
	"credit_in_reporting_currency",
)

SLE_SQL_FIELDS = (
	"name",
	"stock_value",
	"stock_value_difference",
	"incoming_rate",
	"valuation_rate",
	"actual_qty",
	"qty_after_transaction",
)

STE_ITEM_MONETARY = ("amount", "basic_amount")


def sql_get_gl_rows(voucher_type: str, voucher_no: str) -> list[dict]:
	return frappe.db.sql(
		f"""
		select {", ".join(f"`{f}`" for f in GL_SQL_FIELDS)}
		from `tabGL Entry`
		where voucher_type = %s and voucher_no = %s and is_cancelled = 0
		order by creation asc
		""",
		(voucher_type, voucher_no),
		as_dict=True,
	)


def sql_get_sle_rows(voucher_type: str, voucher_no: str) -> list[dict]:
	return frappe.db.sql(
		f"""
		select {", ".join(f"`{f}`" for f in SLE_SQL_FIELDS)}
		from `tabStock Ledger Entry`
		where voucher_type = %s and voucher_no = %s and is_cancelled = 0
		order by creation asc
		""",
		(voucher_type, voucher_no),
		as_dict=True,
	)


def sql_get_stock_entry_header(voucher_no: str) -> dict | None:
	row = frappe.db.sql(
		"""
		select name, purpose, total_incoming_value, total_outgoing_value, value_difference, company
		from `tabStock Entry`
		where name = %s
		""",
		voucher_no,
		as_dict=True,
	)
	return row[0] if row else None


def sql_get_stock_entry_items(voucher_no: str) -> list[dict]:
	return frappe.db.sql(
		"""
		select name, item_code, qty, transfer_qty, amount, basic_amount, s_warehouse, t_warehouse
		from `tabStock Entry Detail`
		where parent = %s
		order by idx asc
		""",
		voucher_no,
		as_dict=True,
	)


def sql_get_stock_entry_rows(voucher_no: str) -> dict:
	return {
		"header": sql_get_stock_entry_header(voucher_no),
		"items": sql_get_stock_entry_items(voucher_no),
	}


def sql_find_fractional_irr_gl(voucher_type: str, voucher_no: str, company: str) -> list[dict]:
	if not is_irr_company(company):
		return []
	company_currency = get_company_currency(company)
	out = []
	for row in sql_get_gl_rows(voucher_type, voucher_no):
		row = dict(row)
		row.setdefault("company", company)
		for field in GL_AMOUNT_FIELDS:
			val = row.get(field)
			if val in (None, ""):
				continue
			cur = currency_for_gl_field(row, field, company_currency)
			if is_irr_currency(cur) and amount_is_fractional(val, cur):
				out.append({"gle": row.get("name"), "field": field, "value": val, "currency": cur})
	return out


def sql_find_fractional_irr_sle(voucher_type: str, voucher_no: str, company: str) -> list[dict]:
	if not is_irr_company(company):
		return []
	company_currency = get_company_currency(company)
	out = []
	for row in sql_get_sle_rows(voucher_type, voucher_no):
		for field in SLE_MONETARY_FIELDS:
			val = row.get(field)
			if val in (None, ""):
				continue
			if amount_is_fractional(val, company_currency):
				out.append({"sle": row.get("name"), "field": field, "value": val})
	return out


def sql_find_fractional_stock_entry_totals(voucher_no: str, company: str) -> list[dict]:
	if not is_irr_company(company):
		return []
	cur = get_company_currency(company)
	out = []
	header = sql_get_stock_entry_header(voucher_no)
	if not header:
		return out
	for f in ("total_incoming_value", "total_outgoing_value", "value_difference"):
		val = header.get(f)
		if val is not None and amount_is_fractional(val, cur):
			out.append({"field": f, "value": val, "where": "tabStock Entry"})
	for item in sql_get_stock_entry_items(voucher_no):
		for f in STE_ITEM_MONETARY:
			val = item.get(f)
			if val is not None and amount_is_fractional(val, cur):
				out.append({"field": f, "value": val, "where": "tabStock Entry Detail", "row": item.get("name")})
	return out


def sql_assert_zero_value_transfer_gl_shape(voucher_no: str, company: str) -> dict:
	header = sql_get_stock_entry_header(voucher_no)
	if not header:
		return {"ok": False, "error": "missing stock entry"}
	purpose = header.get("purpose")
	purposes = ("Material Transfer", "Material Transfer for Manufacture", "Send to Subcontractor")
	is_zero = purpose in purposes and flt(header.get("value_difference")) == 0
	gl_rows = sql_get_gl_rows("Stock Entry", voucher_no)
	debit_total, credit_total = gl_debit_credit_totals(gl_rows)
	cur = get_company_currency(company)
	expected_in = round_currency(header.get("total_incoming_value"), cur)
	expected_out = round_currency(header.get("total_outgoing_value"), cur)

	adj_sql = frappe.db.sql(
		"""
		select name, account, debit, credit
		from `tabGL Entry`
		where voucher_type = 'Stock Entry' and voucher_no = %s and is_cancelled = 0
		and (
			account like %s or account like %s
			or account in (
				select name from `tabAccount`
				where company = %s and account_type in ('Stock Adjustment', 'Round Off')
			)
		)
		""",
		(voucher_no, "%Stock Adjustment%", "%Round Off%", company),
		as_dict=True,
	)
	adj = [r for r in adj_sql if flt(r.debit) or flt(r.credit)]
	adj.extend(stock_adj_round_off_rows(gl_rows, company))
	# de-dupe by name
	seen = set()
	adj_unique = []
	for r in adj:
		n = r.get("name")
		if n in seen:
			continue
		seen.add(n)
		adj_unique.append(r)

	if not is_zero:
		return {
			"applicable": False,
			"ok": True,
			"debit_total": debit_total,
			"credit_total": credit_total,
			"no_adjustment_ok": not adj_unique,
		}

	ok = (
		not adj_unique
		and not is_doubled_gl(debit_total, expected_in)
		and not is_doubled_gl(credit_total, expected_out)
		and flt(debit_total) == flt(expected_in)
		and flt(credit_total) == flt(expected_out)
	)
	return {
		"applicable": True,
		"ok": ok,
		"no_adjustment_ok": not adj_unique,
		"no_double_ok": not is_doubled_gl(debit_total, expected_in)
		and not is_doubled_gl(credit_total, expected_out),
		"adj_rows": adj_unique,
		"debit_total": debit_total,
		"credit_total": credit_total,
		"expected_in": expected_in,
		"expected_out": expected_out,
	}


def sql_gl_grouped_totals(voucher_no: str) -> dict:
	rows = frappe.db.sql(
		"""
		select sum(debit) as debit, sum(credit) as credit
		from `tabGL Entry`
		where voucher_type = 'Stock Entry' and voucher_no = %s and is_cancelled = 0
		""",
		voucher_no,
		as_dict=True,
	)
	return rows[0] if rows else {"debit": 0, "credit": 0}


def sql_sle_grouped_totals(voucher_no: str) -> dict:
	return frappe.db.sql(
		"""
		select sum(stock_value_difference) as svd, sum(stock_value) as sv
		from `tabStock Ledger Entry`
		where voucher_type = 'Stock Entry' and voucher_no = %s and is_cancelled = 0
		""",
		voucher_no,
		as_dict=True,
	)[0]


def comprehensive_voucher_sql_check(
	voucher_type: str, voucher_no: str, company: str, *, zero_value_transfer: bool = False
) -> dict:
	frac_gl = sql_find_fractional_irr_gl(voucher_type, voucher_no, company)
	frac_sle = sql_find_fractional_irr_sle(voucher_type, voucher_no, company)
	frac_ste = (
		sql_find_fractional_stock_entry_totals(voucher_no, company)
		if voucher_type == "Stock Entry"
		else []
	)
	zv = (
		sql_assert_zero_value_transfer_gl_shape(voucher_no, company)
		if voucher_type == "Stock Entry"
		else {"applicable": False, "ok": True}
	)
	db_gl_ok = not frac_gl
	db_sle_ok = not frac_sle
	db_stock_entry_ok = not frac_ste
	no_adjustment_ok = zv.get("no_adjustment_ok", True) if zv.get("applicable") else True
	no_double_ok = zv.get("no_double_ok", True) if zv.get("applicable") else True
	totals_ok = True
	if zv.get("applicable"):
		totals_ok = zv.get("ok", False)
		no_adjustment_ok = zv.get("no_adjustment_ok", False)
		no_double_ok = zv.get("no_double_ok", False)

	return {
		"db_gl_ok": db_gl_ok,
		"db_sle_ok": db_sle_ok,
		"db_stock_entry_ok": db_stock_entry_ok,
		"no_fractional_irr_ok": db_gl_ok and db_sle_ok and db_stock_entry_ok,
		"no_adjustment_ok": no_adjustment_ok,
		"no_double_ok": no_double_ok,
		"totals_ok": totals_ok,
		"zero_value_shape": zv,
		"fractional_gl": frac_gl,
		"fractional_sle": frac_sle,
		"fractional_ste": frac_ste,
	}
