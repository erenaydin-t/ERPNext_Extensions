# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

import frappe
from frappe.utils import cstr

from erpnext_extensions.iran_accounting.account_explorer.dimension_discovery import validate_dimension_field
from erpnext_extensions.iran_accounting.account_explorer.party_sources import get_enabled_party_types
from erpnext_extensions.iran_accounting.account_explorer.schemas import AccountExplorerQuerySpec


def apply_document_scope_filters(query, gle, spec: AccountExplorerQuerySpec):
	query = query.where(gle.company == spec.company)

	if not spec.include_cancelled_entries:
		query = query.where(gle.is_cancelled == 0)

	if not spec.include_period_closing_vouchers:
		query = query.where(gle.voucher_type != "Period Closing Voucher")

	query = _apply_finance_book_filters(query, gle, spec)
	return query


def apply_analysis_scope_filters(
	query,
	gle,
	spec: AccountExplorerQuerySpec,
	*,
	party_types: list[str] | None = None,
):
	accounts = spec.included_account_names or []
	if accounts:
		query = query.where(gle.account.isin(accounts))
	else:
		query = query.where(gle.name == "")

	if party_types is None and spec.view_axis == "party":
		party_types = get_enabled_party_types()
	if party_types:
		query = query.where(gle.party_type.isin(party_types))

	if spec.party_scope.party_type:
		query = query.where(gle.party_type == spec.party_scope.party_type)
	if spec.party_scope.selected_party:
		query = query.where(gle.party == spec.party_scope.selected_party)

	dimension_field = spec.dimension_scope.dimension_field
	if dimension_field:
		validate_dimension_field(dimension_field)
		dim = gle[dimension_field]
		if spec.dimension_scope.selected_value is not None:
			if spec.dimension_scope.selected_value == "":
				query = query.where((dim == "") | (dim.isnull()))
			else:
				query = query.where(dim == spec.dimension_scope.selected_value)

	if spec.voucher_scope.voucher_type:
		query = query.where(gle.voucher_type == spec.voucher_scope.voucher_type)
	if spec.voucher_scope.voucher_no:
		query = query.where(gle.voucher_no == spec.voucher_scope.voucher_no)

	return query


def apply_scoped_gle_filters(
	query,
	gle,
	spec: AccountExplorerQuerySpec,
	*,
	party_types: list[str] | None = None,
):
	query = apply_document_scope_filters(query, gle, spec)
	query = apply_analysis_scope_filters(query, gle, spec, party_types=party_types)
	return query


def get_gl_entry_match_conditions() -> str:
	from frappe.desk.reportview import build_match_conditions

	conditions = build_match_conditions("GL Entry")
	return f" and ({conditions})" if conditions else ""


def apply_opening_period_filters(query, gle, spec: AccountExplorerQuerySpec):
	query = query.where(
		(gle.posting_date < spec.from_date)
		| ((gle.is_opening == "Yes") & (gle.posting_date <= spec.to_date))
	)
	return query


def apply_period_turnover_filters(query, gle, spec: AccountExplorerQuerySpec):
	query = query.where(gle.posting_date >= spec.from_date).where(gle.posting_date <= spec.to_date)
	return apply_opening_entry_filters(query, gle, spec)


def apply_opening_entry_filters(query, gle, spec: AccountExplorerQuerySpec):
	if spec.include_opening_entries:
		query = query.where(
			(gle.is_opening == "No")
			| (
				(gle.is_opening == "Yes")
				& (gle.posting_date >= spec.from_date)
				& (gle.posting_date <= spec.to_date)
			)
		)
	else:
		query = query.where(gle.is_opening == "No")
	return query


def opening_entries_excluded_warning() -> str | None:
	return frappe._("Opening entries are excluded from this voucher view.")


def collect_scope_warnings(spec: AccountExplorerQuerySpec) -> list[str]:
	warnings: list[str] = []
	if not spec.include_opening_entries:
		warning = opening_entries_excluded_warning()
		if warning:
			warnings.append(warning)
	return warnings


def _apply_finance_book_filters(query, gle, spec: AccountExplorerQuerySpec):
	company_fb = frappe.get_cached_value("Company", spec.company, "default_finance_book")

	if spec.include_default_book_entries:
		if spec.finance_book:
			if company_fb and cstr(spec.finance_book) != cstr(company_fb):
				allowed = [spec.finance_book, company_fb, ""]
			else:
				allowed = [spec.finance_book, ""]
			query = query.where((gle.finance_book.isin(allowed)) | gle.finance_book.isnull())
		else:
			allowed = [company_fb, ""] if company_fb else [""]
			query = query.where((gle.finance_book.isin(allowed)) | gle.finance_book.isnull())
	else:
		if spec.finance_book:
			query = query.where((gle.finance_book.isin([spec.finance_book, ""])) | gle.finance_book.isnull())
		else:
			query = query.where((gle.finance_book == "") | gle.finance_book.isnull())
	return query
