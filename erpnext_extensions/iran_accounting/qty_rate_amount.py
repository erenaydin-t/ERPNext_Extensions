# Copyright (c) 2026, ERPNext Extensions contributors
"""Row-level qty × rate monetary rounding (currency precision)."""

from __future__ import annotations

from frappe.utils import flt

import erpnext_extensions.iran_accounting.rounding as rounding
# --- per-doctype row field maps (transaction + company/base where applicable) ---

PI_SI_ITEM_TX_FIELDS = ("rate", "amount", "net_rate", "net_amount")
PI_SI_ITEM_BASE_FIELDS = ("base_rate", "base_amount", "base_net_rate", "base_net_amount")
PO_ITEM_TX_FIELDS = ("rate", "amount", "net_rate", "net_amount")
PO_ITEM_BASE_FIELDS = ("base_rate", "base_amount", "base_net_rate", "base_net_amount")
PR_DN_ITEM_TX_FIELDS = ("rate", "amount")
PR_DN_ITEM_BASE_FIELDS = ("base_rate", "base_amount")
STE_ITEM_FIELDS = ("basic_rate", "basic_amount", "amount", "valuation_rate")


def align_stock_reconciliation_row_amounts(doc) -> None:
	if not rounding.is_irr_company(doc.company):
		return
	currency = rounding.get_company_currency(doc.company)
	total_diff = 0.0
	for row in doc.get("items") or []:
		row.amount = rounding.round_row_amount(row.qty, row.valuation_rate, currency)
		row.current_amount = rounding.round_row_amount(row.current_qty, row.current_valuation_rate, currency)
		row.amount_difference = rounding.round_currency(flt(row.amount) - flt(row.current_amount), currency)
		total_diff += flt(row.amount_difference)
	doc.difference_amount = rounding.round_currency(total_diff, currency)


def align_stock_entry_item_amounts(doc) -> None:
	if not rounding.is_irr_company(doc.company):
		return
	currency = rounding.get_company_currency(doc.company)
	for row in doc.get("items") or []:
		qty = flt(row.qty)
		if row.get("basic_rate") is not None:
			row.basic_amount = rounding.round_row_amount(qty, row.basic_rate, currency)
		rate = row.basic_rate if row.get("basic_rate") is not None else row.get("valuation_rate")
		if rate is not None and row.get("amount") is not None:
			row.amount = rounding.round_row_amount(qty, rate, currency)


def _align_po_pi_si_row(row, company_currency: str, transaction_currency: str) -> None:
	qty = flt(row.qty)
	if row.get("rate") is not None:
		row.rate = rounding.round_currency(row.rate, transaction_currency)
		row.amount = rounding.round_row_amount(qty, row.rate, transaction_currency)
	if row.get("net_rate") is not None:
		row.net_rate = rounding.round_currency(row.net_rate, transaction_currency)
		row.net_amount = rounding.round_row_amount(qty, row.net_rate, transaction_currency)
	for base_field, tx_field in (
		("base_rate", "rate"),
		("base_amount", "amount"),
		("base_net_rate", "net_rate"),
		("base_net_amount", "net_amount"),
	):
		if row.get(tx_field) is not None and row.get(base_field) is not None:
			if transaction_currency == company_currency:
				row.set(base_field, row.get(tx_field))
			else:
				# base = company currency (IRR): round converted or existing base_rate × qty
				br = row.get("base_rate") if base_field.endswith("rate") else None
				if base_field.endswith("amount"):
					src_rate = row.get("base_net_rate" if "net" in base_field else "base_rate")
					row.set(base_field, rounding.round_row_amount(qty, src_rate, company_currency))
				elif br is not None:
					row.set(base_field, rounding.round_currency(br, company_currency))


def align_purchase_order_item_amounts(doc) -> None:
	if not rounding.is_irr_company(doc.company):
		return
	ccy = rounding.get_company_currency(doc.company)
	tx = doc.currency or ccy
	for row in doc.get("items") or []:
		_align_po_pi_si_row(row, ccy, tx)


def align_purchase_invoice_item_amounts(doc) -> None:
	align_purchase_order_item_amounts(doc)


def align_sales_invoice_item_amounts(doc) -> None:
	align_purchase_order_item_amounts(doc)


def align_purchase_receipt_item_amounts(doc) -> None:
	if not rounding.is_irr_company(doc.company):
		return
	ccy = rounding.get_company_currency(doc.company)
	tx = doc.currency or ccy
	for row in doc.get("items") or []:
		qty = flt(row.qty)
		if row.get("rate") is not None:
			row.rate = rounding.round_currency(row.rate, tx)
			row.amount = rounding.round_row_amount(qty, row.rate, tx)
		if row.get("base_rate") is not None:
			row.base_rate = rounding.round_currency(row.base_rate, ccy)
			row.base_amount = rounding.round_row_amount(qty, row.base_rate, ccy)


def align_delivery_note_item_amounts(doc) -> None:
	align_purchase_receipt_item_amounts(doc)


def row_qty_rate_check(
	qty,
	rate,
	stored_amount,
	currency: str,
	*,
	label: str = "amount",
) -> dict:
	raw = flt(qty) * flt(rate)
	expected = rounding.round_row_amount(qty, rate, currency)
	stored = flt(stored_amount) if stored_amount not in (None, "") else None
	residual = None if stored is None else flt(stored) - expected
	precision = rounding.get_currency_precision(currency)
	ok = True
	if stored is not None:
		ok = not rounding.amount_is_fractional(stored, currency) and flt(stored) == flt(expected)
	return {
		"qty": qty,
		"rate": rate,
		"currency": currency,
		"field": label,
		"raw_amount": raw,
		"expected_rounded_amount": expected,
		"stored_amount": stored,
		"residual": residual,
		"status": "PASS" if ok else "FAIL",
	}
