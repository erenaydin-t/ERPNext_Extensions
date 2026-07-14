# Copyright (c) 2026, ERPNext Extensions contributors
"""Stock Ledger vs General Ledger totals for IRR stock vouchers."""

from __future__ import annotations

import frappe
from frappe.utils import flt

from erpnext_extensions.iran_accounting.domain.currency import get_company_currency, is_irr_company
from erpnext_extensions.iran_accounting.domain.stock_entry_sync import (
	assert_stock_entry_row_sle_mirror,
	stock_entry_row_amount,
	sum_stock_entry_row_amounts,
)
from erpnext_extensions.iran_accounting.validation import fetch_gl_rows, gl_debit_credit_totals


def sle_movement_sum(voucher_type: str, voucher_no: str) -> float:
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


def sle_positive_movement_sum(voucher_type: str, voucher_no: str) -> float:
	return flt(
		frappe.db.sql(
			"""
			select coalesce(sum(stock_value_difference), 0)
			from `tabStock Ledger Entry`
			where voucher_type=%s and voucher_no=%s and is_cancelled=0
			  and stock_value_difference > 0
			""",
			(voucher_type, voucher_no),
		)[0][0]
	)


def signed_sle_movement_sum(voucher_type: str, voucher_no: str) -> float:
	return sle_movement_sum(voucher_type, voucher_no)


def assert_stock_entry_ledger_determinism(voucher_no: str, company: str) -> dict:
	"""
	Byte-exact IRR checks: each SLE mirrors row.amount; GL magnitude matches stock movement.
	"""
	if not is_irr_company(company):
		return {"status": "SKIP", "reason": "not IRR"}
	if not frappe.db.exists("Stock Entry", voucher_no):
		return {"status": "FAIL", "reason": "missing Stock Entry"}

	doc = frappe.get_doc("Stock Entry", voucher_no)
	failures = list(assert_stock_entry_row_sle_mirror(voucher_no, company))

	sle_sum = signed_sle_movement_sum("Stock Entry", voucher_no)
	sle_pos = sle_positive_movement_sum("Stock Entry", voucher_no)
	row_gross = sum_stock_entry_row_amounts(doc)

	debit, credit = gl_debit_credit_totals(fetch_gl_rows("Stock Entry", voucher_no))
	gl_mag = max(abs(debit), abs(credit))

	from erpnext_extensions.iran_accounting.zero_value_transfer import (
		ZERO_VALUE_TRANSFER_STOCK_ENTRY_PURPOSES,
		expected_balanced_transfer_gl_magnitude,
	)

	if doc.purpose in ZERO_VALUE_TRANSFER_STOCK_ENTRY_PURPOSES and flt(doc.value_difference) == 0:
		expected_gl = expected_balanced_transfer_gl_magnitude(doc)
		if sle_pos != flt(doc.total_incoming_value):
			failures.append(
				f"transfer incoming SLE {sle_pos} != row total incoming {flt(doc.total_incoming_value)}"
			)
		if gl_mag != expected_gl:
			failures.append(f"GL magnitude {gl_mag} != expected transfer GL {expected_gl}")
	else:
		if abs(sle_sum) != row_gross and doc.purpose in ("Material Receipt", "Material Issue"):
			failures.append(f"|Σ SLE| {abs(sle_sum)} != Σ row.amount {row_gross}")
		if gl_mag != abs(sle_sum):
			failures.append(f"GL magnitude {gl_mag} != |Σ SLE| {abs(sle_sum)}")
		if flt(doc.total_incoming_value) or flt(doc.total_outgoing_value):
			ste_mag = max(flt(doc.total_incoming_value), flt(doc.total_outgoing_value))
			if gl_mag != ste_mag:
				failures.append(f"GL {gl_mag} != Stock Entry header magnitude {ste_mag}")

	for row in doc.items:
		amt = stock_entry_row_amount(row, company)
		if amt != flt(row.amount):
			failures.append(f"row {row.idx}: stored amount {row.amount} != normalized {amt}")

	status = "PASS" if not failures else "FAIL"
	return {
		"status": status,
		"voucher_no": voucher_no,
		"company": company,
		"sle_sum": sle_sum,
		"sle_pos_sum": sle_pos,
		"row_gross_sum": row_gross,
		"gl_magnitude": gl_mag,
		"failures": failures,
	}


def assert_sle_gl_equal(
	voucher_type: str,
	voucher_no: str,
	company: str,
) -> dict:
	"""PASS when stock movement magnitude equals GL magnitude (IRR)."""
	if voucher_type == "Stock Entry":
		out = assert_stock_entry_ledger_determinism(voucher_no, company)
		residual = 0 if out["status"] == "PASS" else 1
		return {
			**out,
			"voucher_type": voucher_type,
			"currency": get_company_currency(company),
			"residual": residual,
		}

	if not is_irr_company(company):
		return {"status": "SKIP", "reason": "not IRR"}
	sle_sum = sle_movement_sum(voucher_type, voucher_no)
	debit, credit = gl_debit_credit_totals(fetch_gl_rows(voucher_type, voucher_no))
	gl_mag = max(abs(debit), abs(credit))
	sle_abs = abs(sle_sum)
	residual = abs(sle_abs - gl_mag)
	status = "PASS" if residual == 0 else "FAIL"
	return {
		"status": status,
		"voucher_type": voucher_type,
		"voucher_no": voucher_no,
		"company": company,
		"currency": get_company_currency(company),
		"sle_sum": sle_sum,
		"sle_abs": sle_abs,
		"gl_debit": debit,
		"gl_credit": credit,
		"gl_magnitude": gl_mag,
		"residual": residual,
	}
