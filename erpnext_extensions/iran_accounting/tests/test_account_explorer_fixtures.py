# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

import json

import frappe

from erpnext_extensions.iran_accounting.account_explorer.constants import DEFAULT_LEVELS, DEFAULT_PARTY_SOURCES


def require_site(test_case) -> str | None:
	if not frappe.db:
		test_case.skipTest("Database not available")
	company = "_Test Company"
	if not frappe.db.exists("Company", company):
		test_case.skipTest("ERPNext _Test Company not available")
	return company


def enable_account_explorer() -> None:
	settings = frappe.get_single("Iran Accounting Settings")
	settings.account_explorer_enabled = 1
	if not settings.account_explorer_levels:
		for row in DEFAULT_LEVELS:
			settings.append(
				"account_explorer_levels",
				{
					"sequence": row["sequence"],
					"enabled": row["enabled"],
					"code_length": row["code_length"],
					"title": row["title"],
					"title_fa": row.get("title_fa"),
					"drill_down_enabled": 1,
					"default_visible": 1,
					"default_sort_order": "code",
				},
			)
	settings.flags.ignore_permissions = True
	settings.save()
	frappe.db.commit()


def enable_wave2a_analysis(*, party: bool = True, dimension: bool = True) -> None:
	enable_account_explorer()
	settings = frappe.get_single("Iran Accounting Settings")
	if party:
		settings.party_analysis_enabled = 1
	if dimension:
		settings.dimension_analysis_enabled = 1
	if not settings.account_explorer_party_sources:
		for row in DEFAULT_PARTY_SOURCES:
			settings.append(
				"account_explorer_party_sources",
				{
					"sequence": row["sequence"],
					"enabled": row["enabled"],
					"party_type": row["party_type"],
					"label": row["label"],
					"label_fa": row.get("label_fa"),
					"show_in_unified_party": 0,
				},
			)
	settings.flags.ignore_permissions = True
	settings.save()
	frappe.db.commit()


def enable_wave2b_voucher(*, include_wave2a: bool = True) -> None:
	if include_wave2a:
		enable_wave2a_analysis()
	else:
		enable_account_explorer()
	settings = frappe.get_single("Iran Accounting Settings")
	settings.voucher_analysis_enabled = 1
	settings.allow_gl_entry_navigation = 1
	settings.flags.ignore_permissions = True
	settings.save()
	frappe.db.commit()


def build_payload(company, fiscal_year, from_date, to_date, analysis=None, document=None):
	document_scope = {
		"company": company,
		"fiscal_year": fiscal_year,
		"from_date": from_date,
		"to_date": to_date,
		"hide_zero_rows": 0,
	}
	if document:
		document_scope.update(document)
	analysis_context = {"view_axis": "account_level"}
	if analysis:
		analysis_context.update(analysis)
	return json.dumps({"document_scope": document_scope, "analysis_context": analysis_context})


def disable_account_explorer() -> None:
	settings = frappe.get_single("Iran Accounting Settings")
	settings.account_explorer_enabled = 0
	settings.flags.ignore_permissions = True
	settings.save()
	frappe.db.commit()


def current_fiscal_year(company: str) -> tuple[str, str, str] | None:
	row = frappe.db.sql(
		"""
		select fy.name, fy.year_start_date, fy.year_end_date
		from `tabFiscal Year` fy
		inner join `tabFiscal Year Company` fyc on fyc.parent = fy.name
		where fyc.company = %s and fy.disabled = 0
		order by fy.year_start_date desc
		limit 1
		""",
		company,
		as_dict=True,
	)
	if not row:
		return None
	return row[0].name, str(row[0].year_start_date), str(row[0].year_end_date)
