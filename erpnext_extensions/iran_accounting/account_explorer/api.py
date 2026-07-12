# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

import frappe

from erpnext_extensions.iran_accounting.account_explorer.dimension_discovery import (
	get_default_dimension_field,
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
	company = frappe.defaults.get_user_default("Company") or frappe.defaults.get_global_default("company")
	fiscal_year = None
	from_date = None
	to_date = None
	if company:
		from erpnext_extensions.iran_accounting.account_explorer.query_spec import _resolve_fiscal_year

		fiscal_year, from_date, to_date = _resolve_fiscal_year(company, None, None, None)

	party_enabled = int(settings.party_analysis_enabled)
	dimension_enabled = int(settings.dimension_analysis_enabled)
	voucher_enabled = int(settings.voucher_analysis_enabled or 0)
	axes = [
		{
			"id": "account_level",
			"label": "Account Levels",
			"enabled": 1,
			"children": levels,
		},
		{"id": "party", "label": "Parties", "enabled": party_enabled},
		{"id": "dimension", "label": "Dimensions", "enabled": dimension_enabled},
		{"id": "voucher", "label": "Vouchers", "enabled": voucher_enabled},
	]

	return {
		"enabled": int(settings.account_explorer_enabled),
		"party_analysis_enabled": party_enabled,
		"dimension_analysis_enabled": dimension_enabled,
		"voucher_analysis_enabled": voucher_enabled,
		"allow_gl_entry_navigation": int(settings.allow_gl_entry_navigation or 0),
		"axes": axes,
		"levels": levels,
		"party_sources": party_sources,
		"dimensions": dimensions,
		"default_dimension_field": get_default_dimension_field(),
		"configuration_warnings": get_identifier_warnings(),
		"defaults": {
			"company": company,
			"fiscal_year": fiscal_year,
			"from_date": str(from_date) if from_date else None,
			"to_date": str(to_date) if to_date else None,
			"hide_zero_rows": int(settings.default_hide_zero_rows),
			"page_size": int(settings.default_page_size) or 50,
			"include_cancelled_entries": int(settings.default_include_cancelled),
			"include_opening_entries": int(settings.default_include_opening_entries),
			"include_period_closing_vouchers": int(settings.default_include_period_closing_vouchers),
		},
		"columns": SUMMARY_COLUMNS,
		"party_columns": PARTY_COLUMNS,
		"dimension_columns": DIMENSION_COLUMNS,
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


def get_dimension_summary(payload) -> dict:
	spec = AccountExplorerQuerySpec_from_client(payload, require_dates=True)
	if spec.view_axis != "dimension":
		frappe.throw(frappe._("Invalid axis for dimension summary."))
	from erpnext_extensions.iran_accounting.account_explorer.dimension_summary import (
		build_dimension_summary,
	)

	result = build_dimension_summary(spec)
	return _summary_response(spec, DIMENSION_COLUMNS, result)


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
		"context": _analysis_context_response(spec),
		**result,
	}


def _analysis_context_response(spec: AccountExplorerQuerySpec) -> dict:
	return {
		"company": spec.company,
		"from_date": str(spec.from_date) if spec.from_date else None,
		"to_date": str(spec.to_date) if spec.to_date else None,
		"fiscal_year": spec.fiscal_year,
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
		"dimension_scope": {
			"dimension_field": spec.dimension_scope.dimension_field,
			"selected_value": spec.dimension_scope.selected_value,
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
		"context": _analysis_context_response(spec),
		**result,
	}


def _grouped_gl_response(spec: AccountExplorerQuerySpec, columns, result: dict) -> dict:
	currency = frappe.get_cached_value("Company", spec.company, "default_currency")
	return {
		"columns": columns,
		"currency": {"code": currency, "precision": frappe.defaults.get_global_default("currency_precision")},
		"context": _analysis_context_response(spec),
		**result,
	}
