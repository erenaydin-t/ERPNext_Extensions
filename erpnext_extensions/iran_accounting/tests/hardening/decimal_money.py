# Copyright (c) 2026, ERPNext Extensions contributors
"""Decimal-only money assertions — no float equality."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any


def D(value: Any) -> Decimal:
	if value is None or value == "":
		return Decimal("0")
	if isinstance(value, Decimal):
		return value
	return Decimal(str(value))


def quantize_money(value: Any, precision: int = 0) -> Decimal:
	q = Decimal("1") if precision == 0 else Decimal(10) ** -precision
	return D(value).quantize(q, rounding=ROUND_HALF_UP)


def money_equal(actual: Any, expected: Any, *, precision: int = 0, label: str = "") -> None:
	a = quantize_money(actual, precision)
	e = quantize_money(expected, precision)
	if a != e:
		raise AssertionError(f"{label or 'money'}: actual={a} expected={e} precision={precision}")


def rate_equal(actual: Any, expected: Any, *, places: int = 9, label: str = "") -> None:
	"""Compare rates with fixed Decimal places (not float almostEqual)."""
	q = Decimal(10) ** -places
	a = D(actual).quantize(q, rounding=ROUND_HALF_UP)
	e = D(expected).quantize(q, rounding=ROUND_HALF_UP)
	if a != e:
		raise AssertionError(f"{label or 'rate'}: actual={a} expected={e} places={places}")


def residual(a: Any, b: Any, *, precision: int = 0) -> Decimal:
	return quantize_money(a, precision) - quantize_money(b, precision)


def compose_amount(basic: Any, additional: Any = 0, lcv: Any = 0, *, precision: int = 0) -> Decimal:
	return quantize_money(D(basic) + D(additional) + D(lcv), precision)


def valuation_from_amount(amount: Any, qty: Any) -> Decimal:
	"""Exact (possibly fractional) amount/qty — prefer ``integer_valuation_rate`` for IRR."""
	qty_d = D(qty)
	if qty_d == 0:
		return Decimal("0")
	return D(amount) / qty_d


def integer_valuation_rate(amount: Any, qty: Any, *, precision: int = 0) -> Decimal:
	"""ROUND_HALF_UP(amount / qty) at currency precision (IRR → integer)."""
	qty_d = D(qty)
	if qty_d == 0:
		return Decimal("0")
	return quantize_money(D(amount) / qty_d, precision)


def rate_first_amount(qty: Any, rate: Any, *, precision: int = 0) -> Decimal:
	"""ROUND_HALF_UP(qty × ROUND_HALF_UP(rate))."""
	return quantize_money(D(qty) * quantize_money(rate, precision), precision)


def amount_vs_rate_qty_residual(amount: Any, qty: Any, valuation_rate: Any, *, precision: int = 0) -> Decimal:
	"""amount − valuation_rate × qty (amount authoritative)."""
	return quantize_money(D(amount) - D(valuation_rate) * D(qty), precision)
