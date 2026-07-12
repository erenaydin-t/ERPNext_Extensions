# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

import frappe
from frappe import _
from frappe.query_builder.functions import Sum
from frappe.utils import flt

from erpnext_extensions.iran_accounting.account_explorer.party_opening import _toggle_debit_credit
from erpnext_extensions.iran_accounting.account_explorer.schemas import AccountExplorerQuerySpec


def _validate_dimension_field(fieldname: str) -> None:
	meta = frappe.get_meta("GL Entry")
	if not meta.has_field(fieldname):
		frappe.throw(_("Dimension field {0} is not available on GL Entry.").format(fieldname))


def _apply_common_filters(query, gle, dim, spec: AccountExplorerQuerySpec, dimension_field: str):
	_validate_dimension_field(dimension_field)
	query = query.where(gle.company == spec.company)
	if not spec.include_cancelled_entries:
		query = query.where(gle.is_cancelled == 0)
	accounts = spec.included_account_names or []
	if accounts:
		query = query.where(gle.account.isin(accounts))
	else:
		query = query.where(gle.name == "")
	if spec.dimension_scope.selected_value is not None:
		if spec.dimension_scope.selected_value == "":
			query = query.where((dim == "") | (dim.isnull()))
		else:
			query = query.where(dim == spec.dimension_scope.selected_value)
	return query


def get_dimension_opening_balances(
	spec: AccountExplorerQuerySpec, dimension_field: str
) -> dict[str, tuple[float, float]]:
	gle = frappe.qb.DocType("GL Entry")
	dim = gle[dimension_field]
	query = frappe.qb.from_(gle).select(
		dim.as_("dimension_value"),
		Sum(gle.debit).as_("opening_debit"),
		Sum(gle.credit).as_("opening_credit"),
	)
	query = _apply_common_filters(query, gle, dim, spec, dimension_field)
	query = query.where(
		(gle.posting_date < spec.from_date)
		| ((gle.is_opening == "Yes") & (gle.posting_date <= spec.to_date))
	).groupby(dim)

	return {
		row.dimension_value or "": _toggle_debit_credit(row.opening_debit, row.opening_credit)
		for row in query.run(as_dict=True)
	}


def get_dimension_period_balances(
	spec: AccountExplorerQuerySpec, dimension_field: str
) -> dict[str, tuple[float, float]]:
	gle = frappe.qb.DocType("GL Entry")
	dim = gle[dimension_field]
	query = frappe.qb.from_(gle).select(
		dim.as_("dimension_value"),
		Sum(gle.debit).as_("period_debit"),
		Sum(gle.credit).as_("period_credit"),
	)
	query = _apply_common_filters(query, gle, dim, spec, dimension_field)
	query = (
		query.where(gle.posting_date >= spec.from_date)
		.where(gle.posting_date <= spec.to_date)
		.where(gle.is_opening == "No")
		.groupby(dim)
	)

	return {
		row.dimension_value or "": (flt(row.period_debit), flt(row.period_credit))
		for row in query.run(as_dict=True)
	}
