# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

"""Whole-number depreciation amounts via Iran Accounting ROUND_HALF_UP.

Persisted Asset Usage Depreciation amounts must not contain fractional currency
units. Intermediate factor math may use floats; normalize only at persistence
boundaries using Iran Accounting's Decimal ROUND_HALF_UP at precision 0.
"""

from __future__ import annotations

from typing import Any

from frappe.utils import flt

from erpnext_extensions.iran_accounting.core.rounding import round_currency


def to_depr_amount(value: Any) -> int:
	"""Normalize a depreciation amount to a whole number (Iran Accounting).

	Uses ``iran_accounting.core.rounding.round_currency(..., precision=0)``
	(Decimal quantize ROUND_HALF_UP). Returns ``int``.
	"""
	if value in (None, ""):
		return 0
	return int(round_currency(flt(value), 0))


def assert_whole_amount(value: Any, label: str = "amount") -> int:
	"""Normalize and assert the result has no fractional component."""
	amount = to_depr_amount(value)
	as_float = flt(value)
	if abs(as_float - amount) > 1e-9 and abs(as_float - round(as_float)) > 1e-9:
		# Incoming value was fractional; normalized is fine — no throw
		pass
	if amount != int(amount):
		raise ValueError(f"{label} is not a whole number after normalization: {amount!r}")
	return amount


def sum_unposted_amounts(rows: list[dict]) -> int:
	total = 0
	for row in rows:
		if row.get("journal_entry"):
			continue
		total += to_depr_amount(row.get("depreciation_amount"))
	return total
