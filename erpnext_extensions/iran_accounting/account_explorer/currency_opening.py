# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

import frappe
from frappe.query_builder.functions import Sum
from frappe.utils import flt

from erpnext_extensions.iran_accounting.account_explorer.gle_filters import (
	apply_opening_period_filters,
	apply_period_turnover_filters,
	apply_scoped_gle_filters,
	get_currency_amount_fields,
	get_currency_group_field,
)
from erpnext_extensions.iran_accounting.account_explorer.party_opening import _toggle_debit_credit
from erpnext_extensions.iran_accounting.account_explorer.schemas import AccountExplorerQuerySpec


def get_currency_opening_balances(
	spec: AccountExplorerQuerySpec, *, currency_type: str = "account_currency"
) -> dict[str, tuple[float, float]]:
	gle = frappe.qb.DocType("GL Entry")
	group_field = get_currency_group_field(currency_type)
	debit_field, credit_field = get_currency_amount_fields(currency_type)
	group_col = gle[group_field]
	debit_col = gle[debit_field]
	credit_col = gle[credit_field]

	query = frappe.qb.from_(gle).select(
		group_col.as_("currency"),
		Sum(debit_col).as_("opening_debit"),
		Sum(credit_col).as_("opening_credit"),
	)
	query = apply_scoped_gle_filters(query, gle, spec)
	query = apply_opening_period_filters(query, gle, spec)
	query = query.where(group_col != "").groupby(group_col)

	return {
		row.currency or "": _toggle_debit_credit(row.opening_debit, row.opening_credit)
		for row in query.run(as_dict=True)
	}


def get_currency_period_balances(
	spec: AccountExplorerQuerySpec, *, currency_type: str = "account_currency"
) -> dict[str, tuple[float, float]]:
	gle = frappe.qb.DocType("GL Entry")
	group_field = get_currency_group_field(currency_type)
	debit_field, credit_field = get_currency_amount_fields(currency_type)
	group_col = gle[group_field]
	debit_col = gle[debit_field]
	credit_col = gle[credit_field]

	query = frappe.qb.from_(gle).select(
		group_col.as_("currency"),
		Sum(debit_col).as_("period_debit"),
		Sum(credit_col).as_("period_credit"),
	)
	query = apply_scoped_gle_filters(query, gle, spec)
	query = apply_period_turnover_filters(query, gle, spec)
	query = query.where(group_col != "").groupby(group_col)

	return {
		row.currency or "": (flt(row.period_debit), flt(row.period_credit))
		for row in query.run(as_dict=True)
	}


def get_currency_company_opening_balances(
	spec: AccountExplorerQuerySpec, *, currency_type: str = "account_currency"
) -> dict[str, tuple[float, float]]:
	"""Opening balances in company currency, grouped by transaction/account currency."""
	gle = frappe.qb.DocType("GL Entry")
	group_field = get_currency_group_field(currency_type)
	group_col = gle[group_field]

	query = frappe.qb.from_(gle).select(
		group_col.as_("currency"),
		Sum(gle.debit).as_("opening_debit"),
		Sum(gle.credit).as_("opening_credit"),
	)
	query = apply_scoped_gle_filters(query, gle, spec)
	query = apply_opening_period_filters(query, gle, spec)
	query = query.where(group_col != "").groupby(group_col)

	return {
		row.currency or "": _toggle_debit_credit(row.opening_debit, row.opening_credit)
		for row in query.run(as_dict=True)
	}


def get_currency_company_period_balances(
	spec: AccountExplorerQuerySpec, *, currency_type: str = "account_currency"
) -> dict[str, tuple[float, float]]:
	"""Period turnover in company currency, grouped by transaction/account currency."""
	gle = frappe.qb.DocType("GL Entry")
	group_field = get_currency_group_field(currency_type)
	group_col = gle[group_field]

	query = frappe.qb.from_(gle).select(
		group_col.as_("currency"),
		Sum(gle.debit).as_("period_debit"),
		Sum(gle.credit).as_("period_credit"),
	)
	query = apply_scoped_gle_filters(query, gle, spec)
	query = apply_period_turnover_filters(query, gle, spec)
	query = query.where(group_col != "").groupby(group_col)

	return {
		row.currency or "": (flt(row.period_debit), flt(row.period_credit))
		for row in query.run(as_dict=True)
	}
