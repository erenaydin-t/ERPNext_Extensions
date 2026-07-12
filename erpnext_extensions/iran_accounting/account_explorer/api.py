# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

import frappe

from erpnext_extensions.iran_accounting.account_explorer.currency_discovery import discover_company_currencies
from erpnext_extensions.iran_accounting.account_explorer.dimension_discovery import (
	get_default_dimension_field,
	get_default_dimension_type,
	get_discovered_dimensions,
)
from erpnext_extensions.iran_accounting.account_explorer.party_sources import (
	get_enabled_party_sources,
	get_identifier_warnings,
)
from erpnext_extensions.iran_accounting.account_explorer.query_builder import (
	build_account_level_summary,
	get_default_level_sequence,
	get_enabled_levels,
)
from erpnext_extensions.iran_accounting.account_explorer.query_spec import (
	AccountExplorerQuerySpec_from_client,
)
from erpnext_extensions.iran_accounting.account_explorer.schemas import AccountExplorerQuerySpec

SUMMARY_COLUMNS = [
	{"id": "display_code", "label": "Code", "fieldtype": "Data", "width": 120},
	{"id": "display_title", "label": "Title", "fieldtype": "Data", "width": 240},
	{"id": "period_debit", "label": "Debit Turnover", "fieldtype": "Currency", "width": 140},
	{"id": "period_credit", "label": "Credit Turnover", "fieldtype": "Currency", "width": 140},
	{"id": "debit_balance", "label": "Debit Balance", "fieldtype": "Currency", "width": 140},
	{"id": "credit_balance", "label": "Credit Balance", "fieldtype": "Currency", "width": 140},
	{"id": "opening_debit", "label": "Opening Debit", "fieldtype": "Currency", "width": 120},
	{"id": "opening_credit", "label": "Opening Credit", "fieldtype": "Currency", "width": 120},
]

PARTY_COLUMNS = [
	{"id": "party_type", "label": "Party Type", "fieldtype": "Data", "width": 120},
	{"id": "display_code", "label": "Party", "fieldtype": "Data", "width": 140},
	{"id": "display_title", "label": "Party Name", "fieldtype": "Data", "width": 220},
	{"id": "party_identifier", "label": "Identifier", "fieldtype": "Data", "width": 140},
	{"id": "period_debit", "label": "Debit Turnover", "fieldtype": "Currency", "width": 140},
	{"id": "period_credit", "label": "Credit Turnover", "fieldtype": "Currency", "width": 140},
	{"id": "debit_balance", "label": "Debit Balance", "fieldtype": "Currency", "width": 140},
	{"id": "credit_balance", "label": "Credit Balance", "fieldtype": "Currency", "width": 140},
]

DIMENSION_COLUMNS = [
	{"id": "display_code", "label": "Code", "fieldtype": "Data", "width": 140},
	{"id": "display_title", "label": "Title", "fieldtype": "Data", "width": 240},
	{"id": "period_debit", "label": "Debit Turnover", "fieldtype": "Currency", "width": 140},
	{"id": "period_credit", "label": "Credit Turnover", "fieldtype": "Currency", "width": 140},
	{"id": "debit_balance", "label": "Debit Balance", "fieldtype": "Currency", "width": 140},
	{"id": "credit_balance", "label": "Credit Balance", "fieldtype": "Currency", "width": 140},
]

UNIFIED_PARTY_COLUMNS = [
	{"id": "display_code", "label": "Code", "fieldtype": "Data", "width": 120},
	{"id": "display_title", "label": "Unified Name", "fieldtype": "Data", "width": 220},
	{"id": "member_count", "label": "Members", "fieldtype": "Int", "width": 90},
	{"id": "primary_member_label", "label": "Primary Member", "fieldtype": "Data", "width": 200},
	{"id": "identifier_summary", "label": "Identifier", "fieldtype": "Data", "width": 140},
	{"id": "period_debit", "label": "Debit Turnover", "fieldtype": "Currency", "width": 140},
	{"id": "period_credit", "label": "Credit Turnover", "fieldtype": "Currency", "width": 140},
	{"id": "debit_balance", "label": "Debit Balance", "fieldtype": "Currency", "width": 140},
	{"id": "credit_balance", "label": "Credit Balance", "fieldtype": "Currency", "width": 140},
]

VOUCHER_COLUMNS = [
	{"id": "posting_date", "label": "Posting Date", "fieldtype": "Date", "width": 110},
	{"id": "voucher_type", "label": "Voucher Type", "fieldtype": "Data", "width": 130},
	{"id": "voucher_no", "label": "Voucher No", "fieldtype": "Data", "width": 140},
	{"id": "party_type", "label": "Party Type", "fieldtype": "Data", "width": 110},
	{"id": "party_name", "label": "Party", "fieldtype": "Data", "width": 180},
	{"id": "voucher_title", "label": "Title", "fieldtype": "Data", "width": 180},
	{"id": "reference", "label": "Reference", "fieldtype": "Data", "width": 140},
	{"id": "scoped_debit", "label": "Scoped Debit", "fieldtype": "Currency", "width": 130},
	{"id": "scoped_credit", "label": "Scoped Credit", "fieldtype": "Currency", "width": 130},
	{"id": "scoped_net", "label": "Scoped Net", "fieldtype": "Currency", "width": 130},
	{"id": "full_voucher_debit", "label": "Full Voucher Debit", "fieldtype": "Currency", "width": 130},
	{"id": "full_voucher_credit", "label": "Full Voucher Credit", "fieldtype": "Currency", "width": 130},
]

GL_GROUP_COLUMNS = [
	{"id": "account", "label": "Account", "fieldtype": "Link", "width": 180},
	{"id": "account_name", "label": "Account Name", "fieldtype": "Data", "width": 180},
	{"id": "party_type", "label": "Party Type", "fieldtype": "Data", "width": 110},
	{"id": "party_name", "label": "Party", "fieldtype": "Data", "width": 160},
	{"id": "dimension_value", "label": "Dimension", "fieldtype": "Data", "width": 140},
	{"id": "debit", "label": "Debit", "fieldtype": "Currency", "width": 120},
	{"id": "credit", "label": "Credit", "fieldtype": "Currency", "width": 120},
	{"id": "against", "label": "Against", "fieldtype": "Data", "width": 220},
]

CURRENCY_COLUMNS = [
	{"id": "currency", "label": "Currency", "fieldtype": "Data", "width": 100},
	{"id": "period_debit", "label": "Debit Turnover", "fieldtype": "Currency", "width": 140},
	{"id": "period_credit", "label": "Credit Turnover", "fieldtype": "Currency", "width": 140},
	{"id": "debit_balance", "label": "Debit Balance", "fieldtype": "Currency", "width": 140},
	{"id": "credit_balance", "label": "Credit Balance", "fieldtype": "Currency", "width": 140},
	{"id": "net_balance", "label": "Net Balance", "fieldtype": "Currency", "width": 140},
]


def get_metadata() -> dict:
	settings = frappe.get_single("Iran Accounting Settings")
	levels = [
		{
			"sequence": int(row.sequence),
			"enabled": int(row.enabled),
			"code_length": int(row.code_length),
			"title": row.title,
			"title_fa": row.title_fa,
			"short_title": row.short_title,
			"drill_down_enabled": int(row.drill_down_enabled),
			"default_visible": int(row.default_visible),
			"default_sort_order": row.default_sort_order,
		}
		for row in get_enabled_levels()
	]
	party_sources = []
	for row in get_enabled_party_sources():
		warning = None
		if row.identifier_field:
			meta = frappe.get_meta(row.party_type)
			if not meta.has_field(row.identifier_field):
				warning = frappe._("Identifier field {0} is missing on {1}.").format(
					row.identifier_field, row.party_type
				)
		party_sources.append(
			{
				"party_type": row.party_type,
				"enabled": int(row.enabled),
				"sequence": int(row.sequence),
				"label": row.label or row.party_type,
				"label_fa": row.label_fa,
				"identifier_field": row.identifier_field,
				"identifier_warning": warning,
				"show_in_unified_party": int(row.show_in_unified_party or 0),
			}
		)
	dimensions = get_discovered_dimensions()
	level_children = [
		{**level, "nav_kind": "account_level"}
		for level in levels
		if level.get("sequence") is not None and "fieldname" not in level
	]
	dimension_children = [
		{
			"fieldname": row["fieldname"],
			"label": row["label"],
			"document_type": row.get("document_type"),
			"nav_kind": "dimension_type",
		}
		for row in dimensions
	]
	company = frappe.defaults.get_user_default("Company") or frappe.defaults.get_global_default("company")
	fiscal_year = None
	from_date = None
	to_date = None
	currencies: list[str] = []
	if company:
		from erpnext_extensions.iran_accounting.account_explorer.query_spec import _resolve_fiscal_year

		fiscal_year, from_date, to_date = _resolve_fiscal_year(company, None, None, None)
		currencies = discover_company_currencies(company)

	party_enabled = int(settings.party_analysis_enabled)
	dimension_enabled = int(settings.dimension_analysis_enabled)
	voucher_enabled = int(settings.voucher_analysis_enabled or 0)
	unified_party_enabled = int(settings.unified_party_enabled or 0)
	currency_enabled = int(settings.currency_analysis_enabled or 0)
	saved_views_enabled = int(settings.saved_views_enabled or 0)
	export_enabled = int(settings.export_enabled or 0)
	export_background_threshold = int(
		settings.export_background_threshold if settings.export_background_threshold is not None else 5000
	)
	diagnostics_enabled = int(settings.diagnostics_enabled or 0)
	axes = [
		{
			"id": "account_level",
			"label": "Account Levels",
			"enabled": 1,
			"children": level_children,
		},
		{"id": "party", "label": "Parties", "enabled": party_enabled},
		{
			"id": "unified_party",
			"label": "Unified Parties",
			"enabled": 1 if party_enabled and unified_party_enabled else 0,
		},
		{
			"id": "dimension",
			"label": "Dimensions",
			"enabled": dimension_enabled,
			"children": dimension_children,
		},
		{"id": "currency", "label": "Currencies", "enabled": currency_enabled},
		{"id": "voucher", "label": "Vouchers", "enabled": voucher_enabled},
	]

	return {
		"enabled": int(settings.account_explorer_enabled),
		"party_analysis_enabled": party_enabled,
		"dimension_analysis_enabled": dimension_enabled,
		"voucher_analysis_enabled": voucher_enabled,
		"unified_party_enabled": unified_party_enabled,
		"currency_analysis_enabled": currency_enabled,
		"saved_views_enabled": saved_views_enabled,
		"export_enabled": export_enabled,
		"export_background_threshold": export_background_threshold,
		"diagnostics_enabled": diagnostics_enabled,
		"allow_gl_entry_navigation": int(settings.allow_gl_entry_navigation or 0),
		"voucher_print_format": settings.account_explorer_voucher_print_format or None,
		"axes": axes,
		"levels": levels,
		"party_sources": party_sources,
		"dimensions": dimensions,
		"currencies": currencies,
		"default_dimension_field": get_default_dimension_field(),
		"default_dimension_type": get_default_dimension_type(),
		"currency_types": [
			{"value": "account_currency", "label": frappe._("Account Currency")},
			{"value": "transaction_currency", "label": frappe._("Transaction Currency")},
		],
		"configuration_warnings": get_identifier_warnings(),
		"defaults": {
			"document_scope": {
				"company": company,
				"fiscal_year": fiscal_year,
				"from_date": str(from_date) if from_date else None,
				"to_date": str(to_date) if to_date else None,
				"hide_zero_rows": int(settings.default_hide_zero_rows),
				"status": {
					"include_cancelled_entries": int(settings.default_include_cancelled),
					"include_opening_entries": int(settings.default_include_opening_entries),
					"include_period_closing_vouchers": int(settings.default_include_period_closing_vouchers),
					"include_default_finance_book_entries": 1,
				},
				"voucher": {},
				"accounting": {},
				"accounting_dimensions": {},
				"currency": {"currency_type": "account_currency", "currency": None},
			},
			"page_size": int(settings.default_page_size) or 50,
		},
		"columns": SUMMARY_COLUMNS,
		"party_columns": PARTY_COLUMNS,
		"unified_party_columns": UNIFIED_PARTY_COLUMNS,
		"dimension_columns": DIMENSION_COLUMNS,
		"currency_columns": CURRENCY_COLUMNS,
		"voucher_columns": VOUCHER_COLUMNS,
		"gl_group_columns": GL_GROUP_COLUMNS,
		"metadata_cache_version": int(settings.metadata_cache_version or 1),
		"default_level_sequence": get_default_level_sequence(),
	}


def validate_document_scope(payload) -> dict:
	spec = AccountExplorerQuerySpec_from_client(payload, require_dates=True)
	return {
		"ok": True,
		"company": spec.company,
		"from_date": str(spec.from_date),
		"to_date": str(spec.to_date),
		"fiscal_year": spec.fiscal_year,
		"scoped_account_count": len(spec.included_account_names or []),
		"document_scope": _document_scope_response(spec),
	}


def get_account_summary(payload) -> dict:
	spec = AccountExplorerQuerySpec_from_client(payload, require_dates=True)
	if spec.view_axis != "account_level":
		frappe.throw(frappe._("Invalid axis for account summary."))
	result = build_account_level_summary(spec)
	return _summary_response(spec, SUMMARY_COLUMNS, result)


def get_party_summary(payload) -> dict:
	spec = AccountExplorerQuerySpec_from_client(payload, require_dates=True)
	if spec.view_axis != "party":
		frappe.throw(frappe._("Invalid axis for party summary."))
	from erpnext_extensions.iran_accounting.account_explorer.party_summary import build_party_summary

	result = build_party_summary(spec)
	return _summary_response(spec, PARTY_COLUMNS, result)


def get_unified_party_summary(payload) -> dict:
	spec = AccountExplorerQuerySpec_from_client(payload, require_dates=True)
	if spec.view_axis != "unified_party":
		frappe.throw(frappe._("Invalid axis for unified party summary."))
	from erpnext_extensions.iran_accounting.account_explorer.unified_party_summary import (
		build_unified_party_summary,
	)

	result = build_unified_party_summary(spec)
	return _summary_response(spec, UNIFIED_PARTY_COLUMNS, result)


def get_unified_party_member_breakdown(payload) -> dict:
	spec = AccountExplorerQuerySpec_from_client(payload, require_dates=True)
	from erpnext_extensions.iran_accounting.account_explorer.permissions import assert_unified_party_enabled

	assert_unified_party_enabled()
	if not spec.unified_party_scope.selected_unified_party:
		frappe.throw(frappe._("Unified Accounting Party is required for member breakdown."))
	from erpnext_extensions.iran_accounting.account_explorer.unified_party_summary import (
		build_unified_party_member_breakdown,
	)

	result = build_unified_party_member_breakdown(spec)
	return _summary_response(spec, PARTY_COLUMNS, result)


def get_unified_party_suggestions(payload) -> dict:
	from erpnext_extensions.iran_accounting.account_explorer.permissions import (
		assert_unified_party_suggestions_allowed,
	)
	from erpnext_extensions.iran_accounting.account_explorer.unified_party_suggestions import (
		build_unified_party_suggestions,
	)

	assert_unified_party_suggestions_allowed()
	data = frappe.parse_json(payload) if isinstance(payload, str) else (payload or {})
	document_scope = data.get("document_scope") or data
	return build_unified_party_suggestions(
		company=document_scope.get("company"),
		limit=data.get("limit") or 50,
	)


def get_dimension_summary(payload) -> dict:
	spec = AccountExplorerQuerySpec_from_client(payload, require_dates=True)
	if spec.view_axis != "dimension":
		frappe.throw(frappe._("Invalid axis for dimension summary."))
	from erpnext_extensions.iran_accounting.account_explorer.dimension_summary import (
		build_dimension_summary,
	)

	result = build_dimension_summary(spec)
	return _summary_response(spec, DIMENSION_COLUMNS, result)


def get_currency_summary(payload) -> dict:
	spec = AccountExplorerQuerySpec_from_client(payload, require_dates=True)
	if spec.view_axis != "currency":
		frappe.throw(frappe._("Invalid axis for currency summary."))
	from erpnext_extensions.iran_accounting.account_explorer.currency_summary import build_currency_summary

	result = build_currency_summary(spec)
	return _summary_response(spec, CURRENCY_COLUMNS, result)


def get_voucher_summary(payload) -> dict:
	spec = AccountExplorerQuerySpec_from_client(payload, require_dates=True)
	if spec.view_axis != "voucher" or spec.detail_mode != "summary":
		frappe.throw(frappe._("Invalid axis for voucher summary."))
	from erpnext_extensions.iran_accounting.account_explorer.voucher_summary import build_voucher_summary

	result = build_voucher_summary(spec)
	return _voucher_response(spec, VOUCHER_COLUMNS, result)


def get_grouped_gl_entries(payload) -> dict:
	spec = AccountExplorerQuerySpec_from_client(payload, require_dates=True)
	if spec.detail_mode != "grouped_gl":
		frappe.throw(frappe._("Invalid detail mode for grouped GL entries."))
	from erpnext_extensions.iran_accounting.account_explorer.voucher_gl import build_grouped_gl_entries

	result = build_grouped_gl_entries(spec)
	return _grouped_gl_response(spec, GL_GROUP_COLUMNS, result)


def get_voucher_navigation_target(payload) -> dict:
	from erpnext_extensions.iran_accounting.account_explorer.voucher_navigation import resolve_voucher_navigation

	return resolve_voucher_navigation(payload)


def get_account_scope_preview(payload) -> dict:
	spec = AccountExplorerQuerySpec_from_client(payload, require_dates=False)
	if spec.requires_bounded_dates():
		spec.included_account_names = spec.included_account_names or []
	return {
		"account_scope": _analysis_context_response(spec)["account_scope"],
		"scoped_account_count": len(spec.included_account_names or []),
	}


def _summary_response(spec: AccountExplorerQuerySpec, columns, result: dict) -> dict:
	currency = frappe.get_cached_value("Company", spec.company, "default_currency")
	return {
		"columns": columns,
		"currency": {"code": currency, "precision": frappe.defaults.get_global_default("currency_precision")},
		"document_scope": _document_scope_response(spec),
		"context": _analysis_context_response(spec),
		**result,
	}


def _document_scope_response(spec: AccountExplorerQuerySpec) -> dict:
	ds = spec.document_scope
	return {
		"company": ds.company,
		"fiscal_year": ds.fiscal_year,
		"from_date": str(ds.from_date) if ds.from_date else None,
		"to_date": str(ds.to_date) if ds.to_date else None,
		"finance_book": ds.finance_book,
		"hide_zero_rows": int(ds.hide_zero_rows),
		"voucher": {
			"voucher_type": ds.voucher.voucher_type,
			"voucher_no": ds.voucher.voucher_no,
			"against_voucher_type": ds.voucher.against_voucher_type,
			"against_voucher_no": ds.voucher.against_voucher_no,
			"reference_no": ds.voucher.reference_no,
		},
		"accounting": {
			"account": ds.accounting.account,
			"party_type": ds.accounting.party_type,
			"party": ds.accounting.party,
		},
		"accounting_dimensions": ds.accounting_dimensions,
		"currency": {
			"currency_type": ds.currency.currency_type,
			"currency": ds.currency.currency,
		},
		"status": {
			"include_opening_entries": int(ds.status.include_opening_entries),
			"include_cancelled_entries": int(ds.status.include_cancelled_entries),
			"include_default_finance_book_entries": int(ds.status.include_default_finance_book_entries),
			"include_period_closing_vouchers": int(ds.status.include_period_closing_vouchers),
		},
	}


def _analysis_context_response(spec: AccountExplorerQuerySpec) -> dict:
	return {
		"view_axis": spec.view_axis,
		"level_sequence": spec.level_sequence,
		"account_scope": {
			"mode": spec.account_scope.mode,
			"selected_account": spec.account_scope.selected_account,
			"virtual_row_key": spec.account_scope.virtual_row_key,
			"is_virtual_group": spec.account_scope.is_virtual_group,
			"level_sequence": spec.account_scope.level_sequence,
			"tree_root_account": spec.account_scope.tree_root_account,
		},
		"party_scope": {
			"party_type": spec.party_scope.party_type,
			"selected_party": spec.party_scope.selected_party,
		},
		"unified_party_scope": {
			"selected_unified_party": spec.unified_party_scope.selected_unified_party,
			"include_unmapped": int(spec.unified_party_scope.include_unmapped),
		},
		"dimension_scope": {
			"dimension_type": spec.dimension_scope.dimension_type,
			"selected_dimension_value": spec.dimension_scope.selected_dimension_value,
		},
		"voucher_scope": {
			"voucher_type": spec.voucher_scope.voucher_type,
			"voucher_no": spec.voucher_scope.voucher_no,
		},
		"detail_mode": spec.detail_mode,
	}


def _voucher_response(spec: AccountExplorerQuerySpec, columns, result: dict) -> dict:
	currency = frappe.get_cached_value("Company", spec.company, "default_currency")
	return {
		"columns": columns,
		"currency": {"code": currency, "precision": frappe.defaults.get_global_default("currency_precision")},
		"document_scope": _document_scope_response(spec),
		"context": _analysis_context_response(spec),
		**result,
	}


def _grouped_gl_response(spec: AccountExplorerQuerySpec, columns, result: dict) -> dict:
	currency = frappe.get_cached_value("Company", spec.company, "default_currency")
	return {
		"columns": columns,
		"currency": {"code": currency, "precision": frappe.defaults.get_global_default("currency_precision")},
		"document_scope": _document_scope_response(spec),
		"context": _analysis_context_response(spec),
		**result,
	}
