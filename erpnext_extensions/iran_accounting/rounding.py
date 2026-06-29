# Copyright (c) 2026, ERPNext Extensions contributors

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

import frappe
from frappe.model.meta import get_field_precision
from frappe.utils import flt

import erpnext
from erpnext.accounts.utils import get_account_currency

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


@frappe.request_cache
def get_currency_precision(currency: str | None) -> int:
	if not currency:
		return get_currency_precision(erpnext.get_default_currency())

	if (currency or "").upper() == "IRR":
		return 0

	system_precision = frappe.db.get_single_value("System Settings", "currency_precision")
	if system_precision not in (None, ""):
		return cint_safe(system_precision)

	use_number_format = frappe.db.get_single_value("System Settings", "use_number_format_from_currency")
	if use_number_format:
		number_format = frappe.db.get_value("Currency", currency, "number_format")
		if number_format:
			return _precision_from_number_format(number_format)

	field = frappe.get_meta("GL Entry").get_field("debit")
	return get_field_precision(field, currency=currency)


def _precision_from_number_format(number_format: str) -> int:
	fmt = number_format or ""
	if "." not in fmt:
		return 0
	return len(fmt.split(".", 1)[1])


def cint_safe(value) -> int:
	try:
		return int(value)
	except (TypeError, ValueError):
		return int(flt(value))


def is_zero_decimal_currency(currency: str | None) -> bool:
	return get_currency_precision(currency) == 0


def is_irr_currency(currency: str | None) -> bool:
	return (currency or "").upper() == "IRR"


def round_currency(value, currency: str | None):
	if value in (None, ""):
		return value
	precision = get_currency_precision(currency)
	if precision == 0:
		return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
	return flt(value, precision)


def get_company_currency(company: str | None) -> str | None:
	if not company:
		return erpnext.get_default_currency()
	return frappe.get_cached_value("Company", company, "default_currency")


def is_irr_company(company: str | None) -> bool:
	return is_irr_currency(get_company_currency(company))


def round_if_irr(value, currency: str | None):
	if is_irr_currency(currency) or (currency is None and is_irr_company(None)):
		return round_currency(value, currency or "IRR")
	return round_currency(value, currency)


def amount_is_fractional(value, currency: str | None) -> bool:
	if value in (None, ""):
		return False
	precision = get_currency_precision(currency)
	rounded = round_currency(value, currency)
	return flt(value, precision + 2) != flt(rounded, precision + 2)


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
		reconcile_irr_sle_after_rounding(sle, company)


def reconcile_irr_sle_after_rounding(sle_doc_or_dict, company: str | None = None) -> None:
	"""Preserve value_before + difference = value_after; derive integer valuation_rate from ending balance."""
	company = company or _get_entry_value(sle_doc_or_dict, "company")
	if not company or not is_irr_company(company):
		return
	qty_raw = _get_entry_value(sle_doc_or_dict, "qty_after_transaction")
	if qty_raw in (None, ""):
		return
	currency = get_company_currency(company)
	qty_after = flt(qty_raw)
	after = flt(_get_entry_value(sle_doc_or_dict, "stock_value"))
	diff = flt(_get_entry_value(sle_doc_or_dict, "stock_value_difference"))
	# Stock ledger engine has not computed balances yet (common on before_insert).
	if not after and not diff:
		_align_stock_reconciliation_incoming_rate(sle_doc_or_dict)
		return
	if not qty_after:
		_set_entry_value(sle_doc_or_dict, "valuation_rate", 0)
		if after:
			before = after - diff
			_set_entry_value(sle_doc_or_dict, "stock_value", 0)
			_set_entry_value(sle_doc_or_dict, "stock_value_difference", -before)
		return
	target_rate = after / qty_after
	candidates = {int(target_rate), int(target_rate) + 1, int(target_rate) - 1, round(target_rate)}
	best_rate = min(
		candidates,
		key=lambda r: abs(after - round_currency(qty_after * r, currency)),
	)
	_set_entry_value(sle_doc_or_dict, "valuation_rate", round_currency(best_rate, currency))
	_align_stock_reconciliation_incoming_rate(sle_doc_or_dict)
	# Keep outgoing_rate integer for IRR issue rows when populated.
	out = flt(_get_entry_value(sle_doc_or_dict, "outgoing_rate"))
	if out and is_irr_company(company):
		_set_entry_value(sle_doc_or_dict, "outgoing_rate", round_currency(out, currency))


def _align_stock_reconciliation_incoming_rate(sle_doc_or_dict) -> None:
	"""ERPNext opening Stock Reconciliation SLEs often keep actual_qty=0; expose rate on incoming_rate."""
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


def round_stock_entry_totals(stock_entry_doc) -> None:
	if not is_irr_company(stock_entry_doc.company):
		return
	currency = get_company_currency(stock_entry_doc.company)
	for field in STOCK_ENTRY_TOTAL_FIELDS:
		if stock_entry_doc.get(field) is not None:
			stock_entry_doc.set(field, round_currency(stock_entry_doc.get(field), currency))
	for row in stock_entry_doc.get("items") or []:
		for field in STOCK_ENTRY_ITEM_MONETARY_FIELDS:
			if row.get(field) is not None:
				row.set(field, round_currency(row.get(field), currency))
