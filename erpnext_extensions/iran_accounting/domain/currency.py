# Copyright (c) 2026, ERPNext Extensions contributors
"""Company/currency precision (Frappe) — uses core.rounding for math."""

from __future__ import annotations

from functools import lru_cache

import erpnext
import frappe
from frappe.utils import cint, cstr, flt

import erpnext_extensions.iran_accounting.core.rounding as core_rounding


@lru_cache(maxsize=256)
def get_currency_precision(currency: str | None) -> int:
	"""Financial precision only — never System Settings or GL field meta."""
	if not currency:
		return get_currency_precision(erpnext.get_default_currency())

	code = (currency or "").upper()
	if code == "IRR":
		return 0

	scfv = frappe.db.get_value("Currency", code, "smallest_currency_fraction_value")
	if scfv not in (None, "", 0):
		return _precision_from_smallest_fraction(scfv)

	# Currency master number_format (not System Settings use_number_format flag)
	number_format = frappe.db.get_value("Currency", code, "number_format")
	if number_format:
		return _precision_from_number_format(number_format)

	return 2


def _precision_from_smallest_fraction(value) -> int:
	"""e.g. 0.01 → 2 decimal places."""
	text = cstr(value).strip()
	if not text or "." not in text:
		return 0
	frac = text.split(".", 1)[1].rstrip("0")
	return len(frac) if frac else 0


def round_row_amount_financial(qty, rate, currency: str | None):
	"""qty × rate at financial precision (IRR integer, FX from Currency master)."""
	return core_rounding.round_row_amount(qty, rate, get_currency_precision(currency))


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
	return core_rounding.round_currency(value, get_currency_precision(currency))


def round_currency_amount(value, currency: str | None):
	return core_rounding.round_currency_amount(value, get_currency_precision(currency))


def round_row_amount(qty, rate, currency: str | None):
	return core_rounding.round_row_amount(qty, rate, get_currency_precision(currency))


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
