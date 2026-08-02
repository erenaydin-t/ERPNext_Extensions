# Copyright (c) 2026, ERPNext Extensions contributors
"""Currency rounding math — stdlib only, safe for worker/web import."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal


def round_currency(value, precision: int):
	if value in (None, ""):
		return value
	if precision == 0:
		return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
	return round(float(value), precision)


def round_currency_amount(value, precision: int):
	"""Round monetary amount to integer/fractional precision."""
	return round_currency(value, precision)


def round_rate(value, precision: int):
	"""Round a monetary rate to currency precision (IRR → integer ROUND_HALF_UP)."""
	return round_currency(value, precision)


def round_row_amount(qty, rate, precision: int):
	"""Rate-first row amount: round(qty × round(rate), precision).

	IRR contract: integer_rate = ROUND_HALF_UP(rate, 0), then
	amount = ROUND_HALF_UP(qty × integer_rate, 0).
	"""
	rounded_rate = round_rate(rate, precision)
	if rounded_rate in (None, ""):
		rounded_rate = 0
	return round_currency(float(qty or 0) * float(rounded_rate), precision)


def rate_qty_amount_residual(amount, qty, valuation_rate, precision: int) -> int | float:
	"""amount − (valuation_rate × qty) at currency precision (amount remains authoritative)."""
	if amount in (None, "") or qty in (None, "") or not float(qty or 0):
		return round_currency(0, precision)
	product = float(valuation_rate or 0) * float(qty)
	return round_currency(float(amount) - product, precision)
