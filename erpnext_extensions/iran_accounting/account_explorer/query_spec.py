# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

import json
from typing import Any

import frappe
from frappe import _
from frappe.utils import cint, getdate

from erpnext_extensions.iran_accounting.account_explorer.account_scope import resolve_account_scope
from erpnext_extensions.iran_accounting.account_explorer.constants import (
	DETAIL_MODES,
	DIMENSION_SORTABLE_FIELDS,
	GL_GROUP_SORTABLE_FIELDS,
	PARTY_SORTABLE_FIELDS,
	SORTABLE_FIELDS,
	VOUCHER_SORTABLE_FIELDS,
	VIEW_AXES,
)
from erpnext_extensions.iran_accounting.account_explorer.dimension_discovery import validate_dimension_field
from erpnext_extensions.iran_accounting.account_explorer.permissions import (
	assert_accounts_role,
	assert_company_allowed,
	assert_dimension_analysis_enabled,
	assert_feature_enabled,
	assert_party_analysis_enabled,
	assert_voucher_analysis_enabled,
)
from erpnext_extensions.iran_accounting.account_explorer.schemas import (
	AccountExplorerQuerySpec,
	AccountScope,
	DimensionScope,
	PaginationState,
	PartyScope,
	VoucherScope,
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


def build_party_scope(raw: dict) -> PartyScope:
	scope_raw = raw.get("party_scope") or {}
	return PartyScope(
		party_type=scope_raw.get("party_type") or None,
		selected_party=scope_raw.get("selected_party") or None,
	)


def build_dimension_scope(raw: dict) -> DimensionScope:
	scope_raw = raw.get("dimension_scope") or {}
	return DimensionScope(
		dimension_field=scope_raw.get("dimension_field") or None,
		selected_value=scope_raw.get("selected_value"),
	)


def build_voucher_scope(raw: dict) -> VoucherScope:
	scope_raw = raw.get("voucher_scope") or {}
	return VoucherScope(
		voucher_type=scope_raw.get("voucher_type") or None,
		voucher_no=scope_raw.get("voucher_no") or None,
	)


def _default_sort_field(view_axis: str, detail_mode: str = "summary") -> str:
	if detail_mode == "grouped_gl":
		return "account"
	if view_axis == "voucher":
		return "posting_date"
	if view_axis == "party":
		return "party_type"
	return "display_code"


def _sortable_fields_for_axis(view_axis: str, detail_mode: str = "summary"):
	if detail_mode == "grouped_gl":
		return GL_GROUP_SORTABLE_FIELDS
	if view_axis == "party":
		return PARTY_SORTABLE_FIELDS
	if view_axis == "dimension":
		return DIMENSION_SORTABLE_FIELDS
	if view_axis == "voucher":
		return VOUCHER_SORTABLE_FIELDS
	return SORTABLE_FIELDS


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
	party_scope = build_party_scope(analysis)
	dimension_scope = build_dimension_scope(analysis)
	voucher_scope = build_voucher_scope(analysis)
	view_axis = analysis.get("view_axis") or "account_level"
	detail_mode = (analysis.get("detail_mode") or "summary").lower()
	if view_axis not in VIEW_AXES:
		raise AccountExplorerValidationError(_("Invalid analysis axis."))
	if detail_mode not in DETAIL_MODES:
		raise AccountExplorerValidationError(_("Invalid detail mode."))
	if view_axis == "party":
		assert_party_analysis_enabled()
	if view_axis == "dimension":
		assert_dimension_analysis_enabled()
		if not dimension_scope.dimension_field:
			raise AccountExplorerValidationError(_("Dimension field is required for dimension analysis."))
		validate_dimension_field(dimension_scope.dimension_field)
	if view_axis == "voucher" or detail_mode == "grouped_gl":
		assert_voucher_analysis_enabled()
	if detail_mode == "grouped_gl":
		if not voucher_scope.voucher_type or not voucher_scope.voucher_no:
			raise AccountExplorerValidationError(
				_("Voucher type and voucher number are required for grouped GL detail.")
			)

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
		party_scope=party_scope,
		dimension_scope=dimension_scope,
		voucher_scope=voucher_scope,
		view_axis=view_axis,
		detail_mode=detail_mode,
		level_sequence=level_sequence,
		pagination=PaginationState(
			page=page,
			page_size=page_size,
			sort_field=(analysis.get("sort_field") or _default_sort_field(view_axis, detail_mode)),
			sort_order=(analysis.get("sort_order") or "asc").lower(),
		),
		presentation_currency=document_scope.get("presentation_currency") or "company",
	)

	if spec.pagination.sort_field not in _sortable_fields_for_axis(view_axis, detail_mode):
		raise AccountExplorerValidationError(_("Invalid sort field."))

	spec.included_account_names = resolve_account_scope(spec)
	return spec
