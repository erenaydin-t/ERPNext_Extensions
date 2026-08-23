# Copyright (c) 2026, Farbod Siyahpoosh and contributors
"""Independent direct-GL baselines for OpeningEntryPolicy acceptance gates."""

from __future__ import annotations

from frappe.utils import cint, flt

from erpnext_extensions.iran_accounting.account_explorer.measures import finalize_measures
from erpnext_extensions.iran_accounting.tests.analytical_parity_fixtures import (
	direct_gl_opening_totals,
	direct_gl_period_totals,
	full_measures_from_opening_period,
)


def direct_gl_policy_measures(
	company: str,
	from_date,
	to_date,
	*,
	include_opening_entries: bool,
	include_cancelled_entries: int = 0,
	include_period_closing_vouchers: int = 0,
	account: str | list[str] | None = None,
	party_type: str | None = None,
	party: str | None = None,
	voucher_type: str | None = None,
	voucher_no: str | None = None,
	cost_center: str | None = None,
	project: str | None = None,
	currency: str | None = None,
	dimension_filters: dict | None = None,
) -> dict[str, float]:
	"""Policy-aligned direct GL totals (never uses Account Explorer builders)."""
	kwargs = {
		"include_opening_entries": 1 if include_opening_entries else 0,
		"include_cancelled_entries": include_cancelled_entries,
		"include_period_closing_vouchers": include_period_closing_vouchers,
		"account": account,
		"party_type": party_type,
		"party": party,
		"voucher_type": voucher_type,
		"voucher_no": voucher_no,
		"cost_center": cost_center,
		"project": project,
		"currency": currency,
		"dimension_filters": dimension_filters,
	}
	opening = direct_gl_opening_totals(company, from_date, to_date, **kwargs)
	period = direct_gl_period_totals(company, from_date, to_date, **kwargs)
	return finalize_measures(full_measures_from_opening_period(opening, period))


def assert_zero_diff(actual: dict, expected: dict, label: str, *, tolerance: float = 1e-6) -> None:
	for field in (
		"opening_debit",
		"opening_credit",
		"period_debit",
		"period_credit",
		"net_balance",
	):
		diff = abs(flt(actual.get(field)) - flt(expected.get(field)))
		if diff > tolerance:
			raise AssertionError(
				f"{label}/{field}: AE={actual.get(field)} GL={expected.get(field)} diff={diff}"
			)


def voucher_axis_direct_totals(
	company: str,
	from_date,
	to_date,
	*,
	include_opening_entries: bool,
	**filters,
) -> dict[str, float]:
	period = direct_gl_period_totals(
		company,
		from_date,
		to_date,
		include_opening_entries=1 if include_opening_entries else 0,
		include_cancelled_entries=filters.get("include_cancelled_entries", 0),
		include_period_closing_vouchers=filters.get("include_period_closing_vouchers", 0),
		account=filters.get("account"),
		party_type=filters.get("party_type"),
		party=filters.get("party"),
		voucher_type=filters.get("voucher_type"),
		voucher_no=filters.get("voucher_no"),
		cost_center=filters.get("cost_center"),
		project=filters.get("project"),
		currency=filters.get("currency"),
		dimension_filters=filters.get("dimension_filters"),
	)
	debit = flt(period["period_debit"])
	credit = flt(period["period_credit"])
	return {
		"scoped_debit": debit,
		"scoped_credit": credit,
		"scoped_net": debit - credit,
	}
