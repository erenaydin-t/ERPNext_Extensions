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


def _prior_warehouse_sle_before(sle) -> tuple[float, float]:
	"""(qty_after_transaction, stock_value) of last SLE before this row."""
	if not sle.item_code or not sle.warehouse or not sle.company:
		return 0.0, 0.0

	name = sle.get("name")
	args = {
		"item_code": sle.item_code,
		"warehouse": sle.warehouse,
		"company": sle.company,
		"posting_date": sle.posting_date,
		"posting_time": sle.posting_time or "00:00:00",
		"creation": sle.creation or "1900-01-01 00:00:00",
		"name": name or "",
	}
	name_clause = "and name != %(name)s" if name else ""
	row = frappe.db.sql(
		f"""
		select qty_after_transaction, stock_value
		from `tabStock Ledger Entry`
		where item_code = %(item_code)s
		  and warehouse = %(warehouse)s
		  and company = %(company)s
		  and is_cancelled = 0
		  {name_clause}
		  and (
			posting_date < %(posting_date)s
			or (posting_date = %(posting_date)s and posting_time < %(posting_time)s)
			or (
				posting_date = %(posting_date)s
				and posting_time = %(posting_time)s
				and creation < %(creation)s
			)
		  )
		order by posting_date desc, posting_time desc, creation desc, name desc
		limit 1
		""",
		args,
	)
	if not row:
		return 0.0, 0.0
	return flt(row[0][0]), flt(row[0][1])


def _warehouse_stock_value_before_sle(sle) -> float:
	return _prior_warehouse_sle_before(sle)[1]


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
	sle.stock_value_difference = amt_diff
	prev_balance = _warehouse_stock_value_before_sle(sle)
	sle.stock_value = round_currency(prev_balance + amt_diff, ccy)


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
