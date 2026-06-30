# Copyright (c) 2026, ERPNext Extensions contributors
"""Leaf helpers for Stock Reconciliation ↔ SLE alignment (no hook/diagnostic imports)."""

from __future__ import annotations

import frappe
from frappe.utils import cint, flt


def sync_irr_sle_from_stock_reconciliation_row(sle) -> None:
	"""Align SLE movement value with rounded Stock Reconciliation Item amount_difference (IRR)."""
	from erpnext_extensions.iran_accounting.rounding import (
		get_company_currency,
		is_irr_company,
		round_currency,
	)

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
