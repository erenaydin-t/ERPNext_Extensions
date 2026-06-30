# Copyright (c) 2026, ERPNext Extensions contributors
"""GL/SLE/stock entry monetary rounding (domain layer)."""

from __future__ import annotations

import frappe
from frappe.utils import flt

from erpnext.accounts.utils import get_account_currency

from erpnext_extensions.iran_accounting.domain.currency import (
	get_company_currency,
	is_irr_company,
	round_currency,
)

GL_AMOUNT_FIELDS = (
	"debit",
	"credit",
	"debit_in_account_currency",
	"credit_in_account_currency",
	"debit_in_transaction_currency",
	"credit_in_transaction_currency",
	"debit_in_reporting_currency",
	"credit_in_reporting_currency",
)

SLE_MONETARY_FIELDS = (
	"stock_value",
	"stock_value_difference",
	"incoming_rate",
	"outgoing_rate",
	"valuation_rate",
)

STOCK_ENTRY_TOTAL_FIELDS = ("total_incoming_value", "total_outgoing_value", "value_difference")
STOCK_ENTRY_ITEM_MONETARY_FIELDS = ("amount", "basic_amount")


def _entry_company(entry) -> str | None:
	if hasattr(entry, "get"):
		return entry.get("company")
	return getattr(entry, "company", None)


def _set_entry_value(entry, field, value):
	if isinstance(entry, dict):
		entry[field] = value
	elif callable(getattr(entry, "set", None)):
		entry.set(field, value)
	else:
		setattr(entry, field, value)


def _get_entry_value(entry, field):
	if hasattr(entry, "get"):
		return entry.get(field)
	return getattr(entry, field, None)


def round_gl_entry_amounts(gl_doc_or_dict) -> None:
	entry = gl_doc_or_dict
	company = _entry_company(entry)
	if not company:
		return

	company_currency = get_company_currency(company)
	account = _get_entry_value(entry, "account")
	account_currency = _get_entry_value(entry, "account_currency")
	if not account_currency and account:
		account_currency = get_account_currency(account)
	account_currency = account_currency or company_currency

	transaction_currency = _get_entry_value(entry, "transaction_currency") or company_currency
	reporting_currency = frappe.get_cached_value("Company", company, "reporting_currency") or company_currency

	for field in ("debit", "credit"):
		val = _get_entry_value(entry, field)
		if val is not None:
			_set_entry_value(entry, field, round_currency(val, company_currency))

	for field in ("debit_in_account_currency", "credit_in_account_currency"):
		val = _get_entry_value(entry, field)
		if val is not None:
			_set_entry_value(entry, field, round_currency(val, account_currency))

	for field in ("debit_in_transaction_currency", "credit_in_transaction_currency"):
		val = _get_entry_value(entry, field)
		if val is not None:
			_set_entry_value(entry, field, round_currency(val, transaction_currency))

	for field in ("debit_in_reporting_currency", "credit_in_reporting_currency"):
		val = _get_entry_value(entry, field)
		if val is not None:
			_set_entry_value(entry, field, round_currency(val, reporting_currency))


def round_sle_monetary_fields(sle_doc_or_dict, company: str | None = None) -> None:
	sle = sle_doc_or_dict
	company = company or _get_entry_value(sle, "company")
	if not company:
		return
	currency = get_company_currency(company)
	for field in SLE_MONETARY_FIELDS:
		val = _get_entry_value(sle, field)
		if val is not None:
			_set_entry_value(sle, field, round_currency(val, currency))
	if is_irr_company(company):
		from erpnext_extensions.iran_accounting.domain.stock_ledger_deterministic import (
			apply_irr_deterministic_sle_valuation,
		)

		apply_irr_deterministic_sle_valuation(sle, company)


def reconcile_irr_sle_after_rounding(sle_doc_or_dict, company: str | None = None) -> None:
	"""Backward-compatible entry: deterministic IRR balance (no engine avg)."""
	from erpnext_extensions.iran_accounting.domain.stock_ledger_deterministic import (
		apply_irr_deterministic_sle_valuation,
	)

	apply_irr_deterministic_sle_valuation(sle_doc_or_dict, company)


def _zero_positive_opening_stock_reconciliation_outgoing_rate(sle_doc_or_dict) -> None:
	if _get_entry_value(sle_doc_or_dict, "voucher_type") != "Stock Reconciliation":
		return
	diff = flt(_get_entry_value(sle_doc_or_dict, "stock_value_difference"))
	actual_qty = flt(_get_entry_value(sle_doc_or_dict, "actual_qty"))
	qty_after = flt(_get_entry_value(sle_doc_or_dict, "qty_after_transaction"))
	if diff > 0:
		_set_entry_value(sle_doc_or_dict, "outgoing_rate", 0)
	elif actual_qty > 0 and diff >= 0:
		_set_entry_value(sle_doc_or_dict, "outgoing_rate", 0)
	elif actual_qty == 0 and qty_after > 0 and diff >= 0:
		_set_entry_value(sle_doc_or_dict, "outgoing_rate", 0)


def _align_stock_reconciliation_incoming_rate(sle_doc_or_dict) -> None:
	voucher_type = _get_entry_value(sle_doc_or_dict, "voucher_type")
	if voucher_type != "Stock Reconciliation":
		return
	if flt(_get_entry_value(sle_doc_or_dict, "qty_after_transaction")) <= 0:
		return
	if flt(_get_entry_value(sle_doc_or_dict, "incoming_rate")):
		return
	rate = flt(_get_entry_value(sle_doc_or_dict, "valuation_rate"))
	if rate > 0:
		_set_entry_value(sle_doc_or_dict, "incoming_rate", rate)
	_zero_positive_opening_stock_reconciliation_outgoing_rate(sle_doc_or_dict)


def round_stock_entry_totals(stock_entry_doc) -> None:
	if not is_irr_company(stock_entry_doc.company):
		return
	currency = get_company_currency(stock_entry_doc.company)
	for row in stock_entry_doc.get("items") or []:
		for field in STOCK_ENTRY_ITEM_MONETARY_FIELDS:
			if row.get(field) is not None:
				row.set(field, round_currency(row.get(field), currency))
	# Header totals = sum of per-row rounded amounts only (no post-aggregation round).
	inc = sum(flt(d.amount) for d in stock_entry_doc.get("items") or [] if d.get("t_warehouse"))
	out = sum(flt(d.amount) for d in stock_entry_doc.get("items") or [] if d.get("s_warehouse"))
	stock_entry_doc.total_incoming_value = inc
	stock_entry_doc.total_outgoing_value = out
	stock_entry_doc.value_difference = inc - out
