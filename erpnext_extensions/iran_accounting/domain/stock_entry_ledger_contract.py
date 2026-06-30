# Copyright (c) 2026, ERPNext Extensions contributors
"""Fail-fast ledger contract: Stock Entry row → SLE → GL (IRR)."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt

from erpnext_extensions.iran_accounting.domain.currency import get_company_currency, is_irr_company
from erpnext_extensions.iran_accounting.domain.stock_entry_sync import (
	assert_stock_entry_row_sle_mirror,
	stock_entry_row_amount,
	sum_stock_entry_row_amounts,
)
from erpnext_extensions.iran_accounting.validation import (
	assert_no_fractional_irr_gl,
	assert_no_fractional_irr_sle,
	fetch_gl_rows,
	fractional_gl_fields,
	fractional_sle_fields,
	gl_debit_credit_totals,
)
from erpnext_extensions.iran_accounting.zero_value_transfer import ZERO_VALUE_TRANSFER_STOCK_ENTRY_PURPOSES


def signed_net_row_amount_sum(doc) -> float:
	"""Σ signed row.amount by warehouse direction (transfer rows excluded from net)."""
	total = 0.0
	for row in doc.get("items") or []:
		amt = stock_entry_row_amount(row, doc.company)
		if row.get("s_warehouse") and row.get("t_warehouse"):
			continue
		if row.get("t_warehouse"):
			total += amt
		elif row.get("s_warehouse"):
			total -= amt
	return total


def expected_header_totals(doc) -> tuple[float, float]:
	"""Incoming/outgoing header = Σ row.amount per leg (no post-sum round)."""
	inc = out = 0.0
	for row in doc.get("items") or []:
		amt = stock_entry_row_amount(row, doc.company)
		if row.get("t_warehouse"):
			inc += amt
		if row.get("s_warehouse"):
			out += amt
	return inc, out


def _gl_stock_account_net(gl_rows: list[dict], company: str) -> float:
	stock_accounts = set(
		frappe.db.sql_list(
			"""
			select name from `tabAccount`
			where company=%s and account_type='Stock' and is_group=0
			""",
			company,
		)
	)
	net = 0.0
	for row in gl_rows:
		if row.get("account") not in stock_accounts:
			continue
		net += flt(row.get("debit")) - flt(row.get("credit"))
	return net


def collect_ledger_contract_failures(voucher_no: str, company: str) -> list[str]:
	if not frappe.db.exists("Stock Entry", voucher_no):
		return [f"Stock Entry {voucher_no} not found"]

	doc = frappe.get_doc("Stock Entry", voucher_no)
	failures = list(assert_stock_entry_row_sle_mirror(voucher_no, company))

	row_gross = sum_stock_entry_row_amounts(doc)
	sle_sum = flt(
		frappe.db.sql(
			"""
			select coalesce(sum(stock_value_difference), 0)
			from `tabStock Ledger Entry`
			where voucher_type='Stock Entry' and voucher_no=%s and is_cancelled=0
			""",
			voucher_no,
		)[0][0]
	)
	sle_pos = flt(
		frappe.db.sql(
			"""
			select coalesce(sum(stock_value_difference), 0)
			from `tabStock Ledger Entry`
			where voucher_type='Stock Entry' and voucher_no=%s and is_cancelled=0
			  and stock_value_difference > 0
			""",
			voucher_no,
		)[0][0]
	)

	signed_net = signed_net_row_amount_sum(doc)
	if doc.purpose in ZERO_VALUE_TRANSFER_STOCK_ENTRY_PURPOSES and flt(doc.value_difference) == 0:
		if sle_sum != 0:
			failures.append(f"transfer Σ SLE movement must be 0, got {sle_sum}")
		if abs(sle_pos - row_gross) != 0:
			failures.append(f"transfer |Σ SLE+| {sle_pos} != Σ row.amount {row_gross}")
	else:
		if sle_sum != signed_net:
			failures.append(f"Σ SLE {sle_sum} != signed Σ row.amount {signed_net}")
		if abs(sle_sum) != row_gross and doc.purpose in ("Material Receipt", "Material Issue"):
			failures.append(f"|Σ SLE| {abs(sle_sum)} != Σ row.amount {row_gross}")

	exp_inc, exp_out = expected_header_totals(doc)
	if flt(doc.total_incoming_value) != exp_inc:
		failures.append(f"header incoming {doc.total_incoming_value} != Σ row.amount in {exp_inc}")
	if flt(doc.total_outgoing_value) != exp_out:
		failures.append(f"header outgoing {doc.total_outgoing_value} != Σ row.amount out {exp_out}")

	for row in doc.items:
		norm = stock_entry_row_amount(row, company)
		if norm != flt(row.amount):
			failures.append(f"row {row.idx}: amount {row.amount} != round(qty×rate) {norm}")

	if doc.docstatus == 1:
		gl_rows = fetch_gl_rows("Stock Entry", voucher_no)
		debit, credit = gl_debit_credit_totals(gl_rows)
		gl_net = debit - credit
		gl_stock_net = _gl_stock_account_net(gl_rows, company)

		if doc.purpose in ZERO_VALUE_TRANSFER_STOCK_ENTRY_PURPOSES and flt(doc.value_difference) == 0:
			if max(debit, credit) != exp_inc:
				failures.append(f"GL magnitude {max(debit, credit)} != incoming total {exp_inc}")
		else:
			if abs(gl_stock_net) != abs(sle_sum):
				failures.append(f"|GL stock net| {abs(gl_stock_net)} != |Σ SLE| {abs(sle_sum)}")
			if gl_net != 0:
				failures.append(f"GL debit-credit net must be 0, got {gl_net}")

		if not assert_no_fractional_irr_gl("Stock Entry", voucher_no, company):
			bad = []
			for row in gl_rows:
				bad.extend(fractional_gl_fields(row, company))
			failures.append(f"fractional IRR in GL: {bad[:3]}")
		if not assert_no_fractional_irr_sle("Stock Entry", voucher_no, company):
			from erpnext_extensions.iran_accounting.validation import fetch_sle_rows, fractional_sle_fields

			bad = []
			for row in fetch_sle_rows("Stock Entry", voucher_no):
				bad.extend(fractional_sle_fields(row, company))
			failures.append(f"fractional IRR in SLE: {bad[:3]}")

	return failures


def enforce_stock_entry_ledger_contract(
	voucher_no: str,
	company: str | None = None,
	*,
	raise_on_fail: bool = True,
) -> dict:
	company = company or frappe.db.get_value("Stock Entry", voucher_no, "company")
	if not is_irr_company(company):
		return {"status": "SKIP", "voucher_no": voucher_no}

	failures = collect_ledger_contract_failures(voucher_no, company)
	status = "PASS" if not failures else "FAIL"
	out = {
		"status": status,
		"voucher_no": voucher_no,
		"company": company,
		"currency": get_company_currency(company),
		"failures": failures,
	}
	if failures and raise_on_fail:
		frappe.throw(
			_("Stock Entry ledger contract violation ({0}): {1}").format(
				voucher_no, "; ".join(failures[:5])
			),
			title=_("IRR Ledger Determinism"),
		)
	return out
