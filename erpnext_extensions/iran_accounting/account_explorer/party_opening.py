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
from erpnext_extensions.iran_accounting.account_explorer.schemas import AccountExplorerQuerySpec


def get_party_opening_balances(spec: AccountExplorerQuerySpec, party_types: list[str]) -> dict[tuple[str, str], tuple[float, float]]:
	if not party_types and not spec.party_scope.selected_party:
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

	opening: dict[tuple[str, str], tuple[float, float]] = {}
	for row in query.run(as_dict=True):
		opening[(row.party_type, row.party)] = _toggle_debit_credit(row.opening_debit, row.opening_credit)
	return opening


def get_party_period_balances(spec: AccountExplorerQuerySpec, party_types: list[str]) -> dict[tuple[str, str], tuple[float, float]]:
	if not party_types and not spec.party_scope.selected_party:
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


def get_unspecified_party_measures(spec: AccountExplorerQuerySpec, party_types: list[str]) -> dict[str, float]:
	"""Aggregate GL lines with no party attribution under the active scoped WHERE.

	Do not pass party_types into apply_scoped_gle_filters: empty-party lines usually also
	have empty party_type and would be incorrectly excluded by party_type IN (...).
	"""
	gle = frappe.qb.DocType("GL Entry")

	def base_query():
		query = frappe.qb.from_(gle)
		# Empty-party lines often also have empty party_type; do not auto-inject
		# party-axis party_type restrictions here.
		query = apply_scoped_gle_filters(
			query, gle, spec, party_types=None, apply_default_party_types=False
		)
		query = query.where((gle.party == "") | (gle.party.isnull()))
		return query

	opening_row = (
		base_query()
		.select(Sum(gle.debit).as_("opening_debit"), Sum(gle.credit).as_("opening_credit"))
		.where(
			(gle.posting_date < spec.from_date)
			| ((gle.is_opening == "Yes") & (gle.posting_date <= spec.to_date))
		)
		.run(as_dict=True)
	)
	period_row = (
		base_query()
		.select(Sum(gle.debit).as_("period_debit"), Sum(gle.credit).as_("period_credit"))
		.where(gle.posting_date >= spec.from_date)
		.where(gle.posting_date <= spec.to_date)
		.where(gle.is_opening == "No")
		.run(as_dict=True)
	)

	opening_debit, opening_credit = _toggle_debit_credit(
		opening_row[0].opening_debit if opening_row else 0,
		opening_row[0].opening_credit if opening_row else 0,
	)
	return {
		"opening_debit": opening_debit,
		"opening_credit": opening_credit,
		"period_debit": flt(period_row[0].period_debit) if period_row else 0,
		"period_credit": flt(period_row[0].period_credit) if period_row else 0,
	}


def _toggle_debit_credit(debit, credit):
	debit = flt(debit)
	credit = flt(credit)
	if debit > credit:
		return debit - credit, 0.0
	return 0.0, credit - debit
