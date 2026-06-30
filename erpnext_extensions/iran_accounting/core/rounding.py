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


def round_row_amount(qty, rate, precision: int):
	"""Row amount = round(qty × rate, precision)."""
	return round_currency(float(qty or 0) * float(rate or 0), precision)
