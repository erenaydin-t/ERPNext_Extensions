# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

import frappe
from frappe.query_builder.functions import Sum
from frappe.utils import flt

from erpnext_extensions.iran_accounting.account_explorer.schemas import AccountExplorerQuerySpec


def _apply_common_filters(query, gle, spec: AccountExplorerQuerySpec, party_types: list[str]):
	query = query.where(gle.company == spec.company)
	if not spec.include_cancelled_entries:
		query = query.where(gle.is_cancelled == 0)
	accounts = spec.included_account_names or []
	if accounts:
		query = query.where(gle.account.isin(accounts))
	else:
		query = query.where(gle.name == "")
	if party_types:
		query = query.where(gle.party_type.isin(party_types))
	if spec.party_scope.party_type:
		query = query.where(gle.party_type == spec.party_scope.party_type)
	if spec.party_scope.selected_party:
		query = query.where(gle.party == spec.party_scope.selected_party)
	return query


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
	query = _apply_common_filters(query, gle, spec, party_types)
	query = query.where(gle.party != "").where(
		(gle.posting_date < spec.from_date)
		| ((gle.is_opening == "Yes") & (gle.posting_date <= spec.to_date))
	)
	query = query.groupby(gle.party_type, gle.party)

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
	query = _apply_common_filters(query, gle, spec, party_types)
	query = (
		query.where(gle.party != "")
		.where(gle.posting_date >= spec.from_date)
		.where(gle.posting_date <= spec.to_date)
		.where(gle.is_opening == "No")
		.groupby(gle.party_type, gle.party)
	)

	return {
		(row.party_type, row.party): (flt(row.period_debit), flt(row.period_credit))
		for row in query.run(as_dict=True)
	}


def get_unspecified_party_measures(spec: AccountExplorerQuerySpec, party_types: list[str]) -> dict[str, float]:
	gle = frappe.qb.DocType("GL Entry")

	def base_query():
		query = frappe.qb.from_(gle).where(gle.company == spec.company)
		if not spec.include_cancelled_entries:
			query = query.where(gle.is_cancelled == 0)
		accounts = spec.included_account_names or []
		if accounts:
			query = query.where(gle.account.isin(accounts))
		else:
			query = query.where(gle.name == "")
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
