# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

import frappe
from frappe.query_builder.functions import Sum
from frappe.utils import flt

from erpnext_extensions.iran_accounting.account_explorer.dimension_discovery import validate_dimension_field
from erpnext_extensions.iran_accounting.account_explorer.gle_filters import (
	apply_opening_period_filters,
	apply_period_turnover_filters,
	apply_scoped_gle_filters,
)
from erpnext_extensions.iran_accounting.account_explorer.party_opening import _toggle_debit_credit
from erpnext_extensions.iran_accounting.account_explorer.schemas import AccountExplorerQuerySpec


def get_dimension_opening_balances(
	spec: AccountExplorerQuerySpec, dimension_field: str
) -> dict[str, tuple[float, float]]:
	validate_dimension_field(dimension_field)
	gle = frappe.qb.DocType("GL Entry")
	dim = gle[dimension_field]
	query = frappe.qb.from_(gle).select(
		dim.as_("dimension_value"),
		Sum(gle.debit).as_("opening_debit"),
		Sum(gle.credit).as_("opening_credit"),
	)
	query = apply_scoped_gle_filters(query, gle, spec)
	query = apply_opening_period_filters(query, gle, spec).groupby(dim)

	return {
		row.dimension_value or "": _toggle_debit_credit(row.opening_debit, row.opening_credit)
		for row in query.run(as_dict=True)
	}


def get_dimension_period_balances(
	spec: AccountExplorerQuerySpec, dimension_field: str
) -> dict[str, tuple[float, float]]:
	validate_dimension_field(dimension_field)
	gle = frappe.qb.DocType("GL Entry")
	dim = gle[dimension_field]
	query = frappe.qb.from_(gle).select(
		dim.as_("dimension_value"),
		Sum(gle.debit).as_("period_debit"),
		Sum(gle.credit).as_("period_credit"),
	)
	query = apply_scoped_gle_filters(query, gle, spec)
	query = apply_period_turnover_filters(query, gle, spec).groupby(dim)

	return {
		row.dimension_value or "": (flt(row.period_debit), flt(row.period_credit))
		for row in query.run(as_dict=True)
	}
