# Copyright (c) 2026, ERPNext Extensions contributors
"""Leaf helpers for Stock Reconciliation ↔ SLE alignment."""

from __future__ import annotations

import frappe
from frappe.utils import cint, flt

from erpnext_extensions.iran_accounting.domain.currency import (
	get_company_currency,
	is_irr_company,
	round_currency,
)


def sync_irr_sle_from_stock_reconciliation_row(sle) -> None:
	if not sle.company or not is_irr_company(sle.company):
		return
	if sle.voucher_type != "Stock Reconciliation" or not sle.voucher_detail_no:
		return
	if cint(sle.get("is_cancelled")):
		return
	row = frappe.db.get_value(
		"Stock Reconciliation Item",
		sle.voucher_detail_no,
		["amount_difference", "amount", "qty"],
		as_dict=True,
	)
	if not row or row.amount_difference in (None, ""):
		return
	ccy = get_company_currency(sle.company)
	amt_diff = round_currency(row.amount_difference, ccy)
	amount = round_currency(row.amount, ccy)
	sle.stock_value_difference = amt_diff
	if flt(sle.qty_after_transaction) and amount:
		sle.stock_value = amount


def assert_stock_reconciliation_row_sle_mirror(voucher_no: str, company: str) -> list[str]:
	"""SLE movement must equal row amount_difference (not engine output)."""
	failures: list[str] = []
	ccy = get_company_currency(company)
	sles = frappe.get_all(
		"Stock Ledger Entry",
		filters={"voucher_type": "Stock Reconciliation", "voucher_no": voucher_no, "is_cancelled": 0},
		fields=["name", "voucher_detail_no", "stock_value_difference"],
	)
	for sle in sles:
		if not sle.voucher_detail_no:
			continue
		row = frappe.db.get_value(
			"Stock Reconciliation Item",
			sle.voucher_detail_no,
			["amount_difference"],
			as_dict=True,
		)
		if not row or row.amount_difference in (None, ""):
			continue
		expected = flt(round_currency(row.amount_difference, ccy))
		if flt(sle.stock_value_difference) != expected:
			failures.append(
				f"SLE {sle.name}: movement {sle.stock_value_difference} != row amount_difference {expected}"
			)
	return failures
