# Copyright (c) 2026, ERPNext Extensions contributors
"""IRR balance qty / stock value / avg rate — valuation_rate rounding only."""

from __future__ import annotations

import frappe
from frappe.utils import flt

from erpnext_extensions.iran_accounting.domain.currency import (
	get_company_currency,
	is_irr_company,
	round_currency,
	round_row_amount_financial,
)
from erpnext_extensions.iran_accounting.domain.ledger_rounding import (
	_get_entry_value,
	_set_entry_value,
	_zero_positive_opening_stock_reconciliation_outgoing_rate,
)


def irr_avg_rate_from_balance(cumulative_value: float, cumulative_qty: float, currency: str) -> float:
	"""Avg rate (balance stock) = round(balance value / qty after transaction, IRR)."""
	if not flt(cumulative_qty) or not flt(cumulative_value):
		return 0.0
	return float(round_currency(flt(cumulative_value) / flt(cumulative_qty), currency))


def _sr_row_balance_amount(sle_doc_or_dict, currency: str) -> float:
	detail_no = _get_entry_value(sle_doc_or_dict, "voucher_detail_no")
	if _get_entry_value(sle_doc_or_dict, "voucher_type") != "Stock Reconciliation" or not detail_no:
		return 0.0
	row = frappe.db.get_value(
		"Stock Reconciliation Item",
		detail_no,
		["amount"],
		as_dict=True,
	)
	if not row or row.amount in (None, ""):
		return 0.0
	return flt(round_currency(row.amount, currency))


def resolve_irr_balance_avg_rate(sle_doc_or_dict, company: str) -> float:
	"""Avg rate from balance value / qty; SR falls back to row.amount when SLE value implies zero avg."""
	currency = get_company_currency(company)
	qty_after = flt(_get_entry_value(sle_doc_or_dict, "qty_after_transaction"))
	if not qty_after:
		return 0.0

	stock_value = flt(_get_entry_value(sle_doc_or_dict, "stock_value"))
	incoming = flt(_get_entry_value(sle_doc_or_dict, "incoming_rate"))
	candidates: list[float] = []
	if stock_value > 0:
		candidates.append(stock_value)
	row_bal = _sr_row_balance_amount(sle_doc_or_dict, currency)
	if row_bal > 0:
		candidates.append(row_bal)
	if incoming > 0 and qty_after > 0:
		candidates.append(flt(round_currency(incoming * qty_after, currency)))

	balance_value = max(candidates) if candidates else 0.0
	if not balance_value:
		return 0.0
	return irr_avg_rate_from_balance(balance_value, qty_after, currency)


def apply_irr_deterministic_sle_valuation(sle_doc_or_dict, company: str | None = None) -> None:
	"""Set valuation_rate from balance stock_value / qty_after_transaction (IRR round only).

	Does not modify stock_value, stock_value_difference, or row amounts — those come from sync/ERPNext.
	"""
	company = company or _get_entry_value(sle_doc_or_dict, "company")
	if not company or not is_irr_company(company):
		return

	currency = get_company_currency(company)
	qty_after = flt(_get_entry_value(sle_doc_or_dict, "qty_after_transaction"))
	stock_value = flt(_get_entry_value(sle_doc_or_dict, "stock_value"))
	movement = flt(_get_entry_value(sle_doc_or_dict, "stock_value_difference"))
	actual_qty = flt(_get_entry_value(sle_doc_or_dict, "actual_qty"))

	prev_qty = qty_after - actual_qty
	prev_value = stock_value - movement

	if not qty_after:
		_set_entry_value(sle_doc_or_dict, "valuation_rate", 0.0)
	else:
		_set_entry_value(
			sle_doc_or_dict,
			"valuation_rate",
			resolve_irr_balance_avg_rate(sle_doc_or_dict, company),
		)

	_set_irr_incoming_rate_from_balance_before(sle_doc_or_dict, company, prev_qty, prev_value, currency)
	_zero_positive_opening_stock_reconciliation_outgoing_rate(sle_doc_or_dict)


def _set_irr_incoming_rate_from_balance_before(
	sle_doc_or_dict,
	company: str,
	prev_qty: float,
	prev_value: float,
	currency: str,
) -> None:
	actual_qty = flt(_get_entry_value(sle_doc_or_dict, "actual_qty"))
	movement = flt(_get_entry_value(sle_doc_or_dict, "stock_value_difference"))
	if actual_qty <= 0 and movement <= 0:
		return

	voucher_type = _get_entry_value(sle_doc_or_dict, "voucher_type")
	detail_no = _get_entry_value(sle_doc_or_dict, "voucher_detail_no")

	if prev_qty > 0 and prev_value > 0:
		incoming = irr_avg_rate_from_balance(prev_value, prev_qty, currency)
	elif voucher_type == "Stock Reconciliation" and detail_no:
		row = frappe.db.get_value(
			"Stock Reconciliation Item",
			detail_no,
			["qty", "valuation_rate", "amount"],
			as_dict=True,
		)
		if row and row.valuation_rate not in (None, ""):
			incoming = float(round_currency(row.valuation_rate, currency))
		elif row and flt(row.qty) and row.amount not in (None, ""):
			incoming = float(
				round_row_amount_financial(flt(row.qty), flt(row.amount) / flt(row.qty), currency)
			)
		else:
			incoming = 0.0
	else:
		incoming = 0.0

	if actual_qty > 0 and incoming:
		_set_entry_value(sle_doc_or_dict, "incoming_rate", incoming)
	elif movement > 0 and flt(_get_entry_value(sle_doc_or_dict, "qty_after_transaction")) > 0 and incoming:
		_set_entry_value(sle_doc_or_dict, "incoming_rate", incoming)
