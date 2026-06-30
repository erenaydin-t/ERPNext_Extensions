# Copyright (c) 2026, ERPNext Extensions contributors
"""IRR balance qty / stock value / avg rate from row-mirrored movements only."""

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
	if not flt(cumulative_qty):
		return 0.0
	return float(round_currency(flt(cumulative_value) / flt(cumulative_qty), currency))


def apply_irr_deterministic_sle_valuation(sle_doc_or_dict, company: str | None = None) -> None:
	"""Balance stock value and avg rate from cumulative row movements (post mirror sync)."""
	company = company or _get_entry_value(sle_doc_or_dict, "company")
	if not company or not is_irr_company(company):
		return

	currency = get_company_currency(company)
	movement = flt(_get_entry_value(sle_doc_or_dict, "stock_value_difference"))
	qty_after = flt(_get_entry_value(sle_doc_or_dict, "qty_after_transaction"))
	actual_qty = flt(_get_entry_value(sle_doc_or_dict, "actual_qty"))
	stock_value = flt(_get_entry_value(sle_doc_or_dict, "stock_value"))

	voucher_type = _get_entry_value(sle_doc_or_dict, "voucher_type")
	if actual_qty == 0 and movement and voucher_type == "Stock Reconciliation":
		prev_qty = 0.0
		prev_value = 0.0
		new_value = float(round_currency(movement, currency))
	else:
		prev_qty = qty_after - actual_qty
		prev_value = stock_value - movement
		new_value = float(round_currency(prev_value + movement, currency))
	if not qty_after:
		_set_entry_value(sle_doc_or_dict, "stock_value", 0.0)
		_set_entry_value(sle_doc_or_dict, "valuation_rate", 0.0)
	else:
		_set_entry_value(sle_doc_or_dict, "stock_value", new_value)
		_set_entry_value(sle_doc_or_dict, "valuation_rate", irr_avg_rate_from_balance(new_value, qty_after, currency))

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
	voucher_no = _get_entry_value(sle_doc_or_dict, "voucher_no")
	detail_no = _get_entry_value(sle_doc_or_dict, "voucher_detail_no")

	if prev_qty > 0:
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
