# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

import frappe

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
	company = frappe.defaults.get_user_default("Company") or frappe.defaults.get_global_default("company")
	fiscal_year = None
	from_date = None
	to_date = None
	if company:
		from erpnext_extensions.iran_accounting.account_explorer.query_spec import _resolve_fiscal_year

		fiscal_year, from_date, to_date = _resolve_fiscal_year(company, None, None, None)

	return {
		"enabled": int(settings.account_explorer_enabled),
		"levels": levels,
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
	result = build_account_level_summary(spec)
	currency = frappe.get_cached_value("Company", spec.company, "default_currency")
	return {
		"columns": SUMMARY_COLUMNS,
		"currency": {"code": currency, "precision": frappe.defaults.get_global_default("currency_precision")},
		"context": _analysis_context_response(spec),
		**result,
	}


def get_account_scope_preview(payload) -> dict:
	spec = AccountExplorerQuerySpec_from_client(payload, require_dates=False)
	if spec.requires_bounded_dates():
		spec.included_account_names = spec.included_account_names or []
	return {
		"account_scope": _analysis_context_response(spec)["account_scope"],
		"scoped_account_count": len(spec.included_account_names or []),
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
	}
