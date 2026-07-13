# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

import frappe
from frappe.query_builder.functions import Sum
from frappe.utils import flt

from erpnext_extensions.iran_accounting.account_explorer.gle_filters import (
	apply_opening_period_filters,
	apply_period_turnover_filters,
	apply_scoped_gle_filters,
)
from erpnext_extensions.iran_accounting.account_explorer.party_opening import _toggle_debit_credit
from erpnext_extensions.iran_accounting.account_explorer.schemas import AccountExplorerQuerySpec
from erpnext_extensions.iran_accounting.account_explorer.unified_party_registry import get_unified_party_types


def get_party_period_balances(
	spec: AccountExplorerQuerySpec, party_types: list[str] | None = None
) -> dict[tuple[str, str], tuple[float, float]]:
	party_types = party_types or get_unified_party_types()
	if not party_types:
		return {}

	gle = frappe.qb.DocType("GL Entry")
	query = frappe.qb.from_(gle).select(
		gle.party_type,
		gle.party,
		Sum(gle.debit).as_("period_debit"),
		Sum(gle.credit).as_("period_credit"),
	)
	query = apply_scoped_gle_filters(query, gle, spec, party_types=party_types)
	query = apply_period_turnover_filters(query, gle, spec)
	query = query.where(gle.party != "").groupby(gle.party_type, gle.party)

	return {
		(row.party_type, row.party): (flt(row.period_debit), flt(row.period_credit))
		for row in query.run(as_dict=True)
	}


def get_party_opening_balances(
	spec: AccountExplorerQuerySpec, party_types: list[str] | None = None
) -> dict[tuple[str, str], tuple[float, float]]:
	party_types = party_types or get_unified_party_types()
	if not party_types:
		return {}

	gle = frappe.qb.DocType("GL Entry")
	query = frappe.qb.from_(gle).select(
		gle.party_type,
		gle.party,
		Sum(gle.debit).as_("opening_debit"),
		Sum(gle.credit).as_("opening_credit"),
	)
	query = apply_scoped_gle_filters(query, gle, spec, party_types=party_types)
	query = apply_opening_period_filters(query, gle, spec)
	query = query.where(gle.party != "").groupby(gle.party_type, gle.party)

	return {
		(row.party_type, row.party): _toggle_debit_credit(row.opening_debit, row.opening_credit)
		for row in query.run(as_dict=True)
	}


def rollup_measures_for_members(
	member_tuples: list[tuple[str, str]],
	opening: dict[tuple[str, str], tuple[float, float]],
	period: dict[tuple[str, str], tuple[float, float]],
) -> tuple[float, float, float, float]:
	opening_debit = opening_credit = period_debit = period_credit = 0.0
	for key in member_tuples:
		open_vals = opening.get(key, (0.0, 0.0))
		period_vals = period.get(key, (0.0, 0.0))
		opening_debit += flt(open_vals[0])
		opening_credit += flt(open_vals[1])
		period_debit += flt(period_vals[0])
		period_credit += flt(period_vals[1])
	return opening_debit, opening_credit, period_debit, period_credit
