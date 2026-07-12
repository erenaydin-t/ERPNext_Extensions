# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

import json
from typing import Any

import frappe
from frappe import _
from frappe.utils import cint, getdate

from erpnext_extensions.iran_accounting.account_explorer.account_scope import resolve_account_scope
from erpnext_extensions.iran_accounting.account_explorer.constants import SORTABLE_FIELDS
from erpnext_extensions.iran_accounting.account_explorer.permissions import (
	assert_accounts_role,
	assert_company_allowed,
	assert_feature_enabled,
)
from erpnext_extensions.iran_accounting.account_explorer.schemas import (
	AccountExplorerQuerySpec,
	AccountScope,
	PaginationState,
)


class AccountExplorerValidationError(frappe.ValidationError):
	pass


def _parse_json(value: Any) -> dict:
	if not value:
		return {}
	if isinstance(value, dict):
		return value
	if isinstance(value, str):
		return json.loads(value) if value.strip() else {}
	return {}


def _resolve_fiscal_year(
	company: str, fiscal_year: str | None, from_date, to_date
) -> tuple[str | None, Any, Any]:
	if fiscal_year:
		fy = frappe.get_cached_value(
			"Fiscal Year",
			fiscal_year,
			["year_start_date", "year_end_date"],
			as_dict=True,
		)
		if not fy:
			frappe.throw(_("Fiscal Year {0} does not exist").format(fiscal_year))
		start = getdate(fy.year_start_date)
		end = getdate(fy.year_end_date)
		return fiscal_year, from_date or start, to_date or end

	if from_date and to_date:
		return fiscal_year, getdate(from_date), getdate(to_date)

	current = frappe.db.sql(
		"""
		select fy.name, fy.year_start_date, fy.year_end_date
		from `tabFiscal Year` fy
		inner join `tabFiscal Year Company` fyc on fyc.parent = fy.name
		where fyc.company = %s and fy.disabled = 0
		  and %s between fy.year_start_date and fy.year_end_date
		order by fy.year_start_date desc
		limit 1
		""",
		(company, getdate()),
		as_dict=True,
	)
	if current:
		row = current[0]
		return row.name, getdate(row.year_start_date), getdate(row.year_end_date)
	return fiscal_year, from_date, to_date


def _load_settings_defaults() -> dict:
	settings = frappe.get_single("Iran Accounting Settings")
	return {
		"include_cancelled_entries": cint(settings.default_include_cancelled),
		"hide_zero_rows": cint(settings.default_hide_zero_rows),
		"page_size": cint(settings.default_page_size) or 50,
		"include_opening_entries": cint(settings.default_include_opening_entries),
		"include_period_closing_vouchers": cint(settings.default_include_period_closing_vouchers),
	}


def build_account_scope(raw: dict) -> AccountScope:
	scope_raw = raw.get("account_scope") or {}
	return AccountScope(
		mode=scope_raw.get("mode") or "tree",
		selected_account=scope_raw.get("selected_account"),
		virtual_row_key=scope_raw.get("virtual_row_key"),
		is_virtual_group=cint(scope_raw.get("is_virtual_group")),
		level_sequence=cint(scope_raw.get("level_sequence")) or None,
		tree_root_account=scope_raw.get("tree_root_account") or scope_raw.get("selected_account"),
	)


def AccountExplorerQuerySpec_from_client(
	payload: Any, *, require_dates: bool = True
) -> AccountExplorerQuerySpec:
	assert_accounts_role()
	data = _parse_json(payload)
	document_scope = data.get("document_scope") or data
	analysis = data.get("analysis_context") or data

	company = document_scope.get("company") or analysis.get("company")
	if not company:
		raise AccountExplorerValidationError(_("Company is required."))

	assert_company_allowed(company)
	assert_feature_enabled()

	defaults = _load_settings_defaults()

	from_date = document_scope.get("from_date")
	to_date = document_scope.get("to_date")
	fiscal_year = document_scope.get("fiscal_year")
	fiscal_year, from_date, to_date = _resolve_fiscal_year(company, fiscal_year, from_date, to_date)

	if require_dates and (not from_date or not to_date):
		raise AccountExplorerValidationError(
			_("From Date and To Date are required before running Account Explorer queries.")
		)

	if from_date and to_date and getdate(from_date) > getdate(to_date):
		raise AccountExplorerValidationError(_("From Date cannot be greater than To Date"))

	account_scope = build_account_scope(analysis)
	level_sequence = analysis.get("level_sequence")
	if level_sequence is not None:
		level_sequence = cint(level_sequence) or None

	page = max(cint(analysis.get("page") or document_scope.get("page") or 1), 1)
	page_size = (
		cint(analysis.get("page_size") or document_scope.get("page_size") or defaults["page_size"]) or 50
	)
	page_size = min(
		page_size, cint(frappe.get_single_value("Iran Accounting Settings", "server_page_size")) or 200
	)

	spec = AccountExplorerQuerySpec(
		company=company,
		from_date=getdate(from_date) if from_date else None,
		to_date=getdate(to_date) if to_date else None,
		fiscal_year=fiscal_year,
		finance_book=document_scope.get("finance_book"),
		include_default_book_entries=cint(document_scope.get("include_default_book_entries", 1)),
		include_cancelled_entries=cint(
			document_scope.get("include_cancelled_entries", defaults["include_cancelled_entries"])
		),
		include_opening_entries=cint(
			document_scope.get("include_opening_entries", defaults["include_opening_entries"])
		),
		include_period_closing_vouchers=cint(
			document_scope.get(
				"include_period_closing_vouchers",
				defaults["include_period_closing_vouchers"],
			)
		),
		hide_zero_rows=cint(document_scope.get("hide_zero_rows", defaults["hide_zero_rows"])),
		account_scope=account_scope,
		view_axis=analysis.get("view_axis") or "account_level",
		level_sequence=level_sequence,
		pagination=PaginationState(
			page=page,
			page_size=page_size,
			sort_field=(analysis.get("sort_field") or "display_code"),
			sort_order=(analysis.get("sort_order") or "asc").lower(),
		),
		presentation_currency=document_scope.get("presentation_currency") or "company",
	)

	if spec.pagination.sort_field not in SORTABLE_FIELDS:
		raise AccountExplorerValidationError(_("Invalid sort field."))

	spec.included_account_names = resolve_account_scope(spec)
	return spec
