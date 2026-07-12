# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

import frappe
from frappe.utils import cstr

from erpnext_extensions.iran_accounting.account_explorer.dimension_discovery import validate_dimension_field
from erpnext_extensions.iran_accounting.account_explorer.party_sources import get_enabled_party_types
from erpnext_extensions.iran_accounting.account_explorer.schemas import AccountExplorerQuerySpec, DocumentScope
from erpnext_extensions.iran_accounting.account_explorer.unified_party_registry import get_unified_party_types


def normalize_filter_values(value) -> list[str]:
	if value is None or value == "":
		return []
	if isinstance(value, (list, tuple, set)):
		return [str(item) for item in value if item not in (None, "")]
	return [str(value)]


def apply_member_tuple_filter(query, gle, member_tuples: list[tuple[str, str]]):
	if not member_tuples:
		return query.where(gle.name == "")
	condition = None
	for party_type, party in member_tuples:
		part = (gle.party_type == party_type) & (gle.party == party)
		condition = part if condition is None else condition | part
	return query.where(condition)


def apply_document_scope_filters(query, gle, spec: AccountExplorerQuerySpec):
	document_scope = spec.document_scope
	query = query.where(gle.company == document_scope.company)

	if not document_scope.status.include_cancelled_entries:
		query = query.where(gle.is_cancelled == 0)

	if not document_scope.status.include_period_closing_vouchers:
		query = query.where(gle.voucher_type != "Period Closing Voucher")

	query = _apply_finance_book_filters(query, gle, document_scope)
	query = _apply_document_voucher_filters(query, gle, document_scope)
	query = _apply_document_accounting_filters(query, gle, document_scope)
	query = _apply_document_dimension_filters(query, gle, document_scope)
	query = _apply_document_currency_filters(query, gle, document_scope)
	return query


def _apply_document_voucher_filters(query, gle, document_scope: DocumentScope):
	voucher = document_scope.voucher
	if voucher.voucher_type:
		query = query.where(gle.voucher_type == voucher.voucher_type)
	if voucher.voucher_no:
		query = query.where(gle.voucher_no == voucher.voucher_no)
	if voucher.against_voucher_type:
		query = query.where(gle.against_voucher_type == voucher.against_voucher_type)
	if voucher.against_voucher_no:
		query = query.where(gle.against_voucher == voucher.against_voucher_no)
	if voucher.reference_no:
		gl_meta = frappe.get_meta("GL Entry")
		if gl_meta.has_field("bill_no"):
			query = query.where(gle.bill_no == voucher.reference_no)
	return query


def _apply_document_accounting_filters(query, gle, document_scope: DocumentScope):
	accounting = document_scope.accounting
	accounts = normalize_filter_values(accounting.account)
	if accounts:
		query = query.where(gle.account.isin(accounts))
	if accounting.party_type:
		query = query.where(gle.party_type == accounting.party_type)
	parties = normalize_filter_values(accounting.party)
	if parties:
		query = query.where(gle.party.isin(parties))
	return query


def _apply_document_dimension_filters(query, gle, document_scope: DocumentScope):
	for fieldname, value in (document_scope.accounting_dimensions or {}).items():
		if value is None or value == "":
			continue
		validate_dimension_field(fieldname)
		dim = gle[fieldname]
		values = normalize_filter_values(value)
		if not values:
			continue
		if len(values) == 1:
			query = query.where(dim == values[0])
		else:
			query = query.where(dim.isin(values))
	return query


def _apply_document_currency_filters(query, gle, document_scope: DocumentScope):
	currency = document_scope.currency
	if not currency.currency:
		return query
	if currency.currency_type == "transaction_currency":
		query = query.where(
			(gle.transaction_currency == currency.currency)
			| ((gle.transaction_currency.isnull() | (gle.transaction_currency == "")) & (gle.account_currency == currency.currency))
		)
	else:
		query = query.where(gle.account_currency == currency.currency)
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

	if spec.resolved_member_tuples:
		query = apply_member_tuple_filter(query, gle, spec.resolved_member_tuples)
	else:
		if party_types is None:
			if spec.view_axis == "unified_party":
				party_types = get_unified_party_types()
			elif spec.view_axis == "party":
				party_types = get_enabled_party_types()
		if party_types:
			query = query.where(gle.party_type.isin(party_types))

		if spec.view_axis != "unified_party":
			if spec.party_scope.party_type:
				query = query.where(gle.party_type == spec.party_scope.party_type)
			if spec.party_scope.selected_party:
				query = query.where(gle.party == spec.party_scope.selected_party)

	dimension_type = spec.dimension_scope.dimension_type
	if dimension_type and spec.dimension_scope.selected_dimension_value is not None:
		validate_dimension_field(dimension_type)
		dim = gle[dimension_type]
		if spec.dimension_scope.selected_dimension_value == "":
			query = query.where((dim == "") | (dim.isnull()))
		else:
			query = query.where(dim == spec.dimension_scope.selected_dimension_value)

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


def get_currency_amount_fields(currency_type: str = "account_currency") -> tuple[str, str]:
	if currency_type == "transaction_currency":
		return "debit_in_transaction_currency", "credit_in_transaction_currency"
	return "debit_in_account_currency", "credit_in_account_currency"


def get_currency_group_field(currency_type: str = "account_currency") -> str:
	return "transaction_currency" if currency_type == "transaction_currency" else "account_currency"


def _apply_finance_book_filters(query, gle, document_scope: DocumentScope):
	company_fb = frappe.get_cached_value("Company", document_scope.company, "default_finance_book")

	if document_scope.status.include_default_finance_book_entries:
		if document_scope.finance_book:
			if company_fb and cstr(document_scope.finance_book) != cstr(company_fb):
				allowed = [document_scope.finance_book, company_fb, ""]
			else:
				allowed = [document_scope.finance_book, ""]
			query = query.where((gle.finance_book.isin(allowed)) | gle.finance_book.isnull())
		else:
			allowed = [company_fb, ""] if company_fb else [""]
			query = query.where((gle.finance_book.isin(allowed)) | gle.finance_book.isnull())
	else:
		if document_scope.finance_book:
			query = query.where((gle.finance_book.isin([document_scope.finance_book, ""])) | gle.finance_book.isnull())
		else:
			query = query.where((gle.finance_book == "") | gle.finance_book.isnull())
	return query
