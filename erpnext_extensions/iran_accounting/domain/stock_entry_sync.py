# Copyright (c) 2026, ERPNext Extensions contributors
"""Stock Entry: capitalization-aware row.amount is the source for SLE movement (IRR)."""

from __future__ import annotations

import frappe
from frappe.utils import cint, flt

from erpnext_extensions.iran_accounting.domain.currency import (
	get_company_currency,
	is_irr_company,
	round_currency,
	round_row_amount_financial,
)


def stock_entry_row_amount(row, company: str) -> float:
	"""Capitalization-aware row amount for SLE/GL mirroring.

	Prefer stored ``amount`` (already ERPNext composition after align).
	If missing, recompose: basic_amount + additional_cost + landed_cost_voucher_amount,
	with basic_amount from transfer_qty × basic_rate when needed.
	"""
	ccy = get_company_currency(company)
	if row.get("amount") not in (None, ""):
		return float(round_currency(row.amount, ccy))

	transfer_qty = flt(
		row.get("transfer_qty") if row.get("transfer_qty") not in (None, "") else row.get("qty")
	)
	basic_amount = row.get("basic_amount")
	if basic_amount in (None, "") and transfer_qty and row.get("basic_rate") not in (None, ""):
		basic_amount = round_row_amount_financial(transfer_qty, row.basic_rate, ccy)
	composed = (
		flt(basic_amount)
		+ flt(row.get("additional_cost"))
		+ flt(row.get("landed_cost_voucher_amount"))
	)
	if composed:
		return float(round_currency(composed, ccy))
	return 0.0


def signed_movement_from_row_amount(magnitude: float, actual_qty: float) -> float:
	if actual_qty < 0:
		return -abs(magnitude)
	if actual_qty > 0:
		return abs(magnitude)
	return 0.0


def sync_irr_sle_from_stock_entry_row(sle) -> None:
	"""SLE movement mirrors signed row.amount (never raw engine output). Idempotent."""
	if not sle.company or not is_irr_company(sle.company):
		return
	if sle.voucher_type != "Stock Entry" or not sle.voucher_detail_no:
		return
	if cint(sle.get("is_cancelled")):
		return

	row = frappe.db.get_value(
		"Stock Entry Detail",
		sle.voucher_detail_no,
		[
			"qty",
			"transfer_qty",
			"basic_rate",
			"basic_amount",
			"additional_cost",
			"landed_cost_voucher_amount",
			"valuation_rate",
			"amount",
		],
		as_dict=True,
	)
	if not row:
		return

	ccy = get_company_currency(sle.company)
	magnitude = stock_entry_row_amount(row, sle.company)

	movement = round_currency(signed_movement_from_row_amount(magnitude, flt(sle.actual_qty)), ccy)
	if flt(sle.stock_value_difference) == movement and flt(sle.stock_value) == round_currency(
		flt(sle.stock_value), ccy
	):
		return
	value_after = flt(sle.stock_value)
	value_before = value_after - flt(sle.stock_value_difference)
	sle.stock_value_difference = movement
	sle.stock_value = round_currency(value_before + movement, ccy)


def gl_movement_from_row_only(item_row, sle, company: str) -> float:
	"""GL debit/credit leg from row.amount + SLE sign (actual_qty); no SLE magnitude fallback."""
	magnitude = stock_entry_row_amount(item_row, company)
	return signed_movement_from_row_amount(magnitude, flt(sle.actual_qty))


def sum_stock_entry_row_amounts(doc) -> float:
	"""Σ positive row.amount (gross); for transfers compare to incoming leg."""
	total = 0.0
	for row in doc.get("items") or []:
		total += stock_entry_row_amount(row, doc.company)
	return total


def assert_stock_entry_row_sle_mirror(voucher_no: str, company: str) -> list[str]:
	failures = []
	sles = frappe.get_all(
		"Stock Ledger Entry",
		filters={"voucher_type": "Stock Entry", "voucher_no": voucher_no, "is_cancelled": 0},
		fields=["name", "voucher_detail_no", "actual_qty", "stock_value_difference"],
	)
	for sle in sles:
		if not sle.voucher_detail_no:
			continue
		row = frappe.db.get_value(
			"Stock Entry Detail",
			sle.voucher_detail_no,
			[
				"qty",
				"transfer_qty",
				"basic_rate",
				"basic_amount",
				"additional_cost",
				"landed_cost_voucher_amount",
				"valuation_rate",
				"amount",
			],
			as_dict=True,
		)
		if not row:
			continue
		mag = stock_entry_row_amount(row, company)
		expected = signed_movement_from_row_amount(mag, flt(sle.actual_qty))
		if flt(sle.stock_value_difference) != expected:
			failures.append(f"SLE {sle.name}: movement {sle.stock_value_difference} != row mirror {expected}")
	return failures


# Backward-compatible alias
irr_gl_movement_amount = gl_movement_from_row_only
