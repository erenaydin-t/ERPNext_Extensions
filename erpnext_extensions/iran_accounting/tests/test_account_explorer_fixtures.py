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


def enable_wave2c_unified_party(*, include_wave2b: bool = True) -> None:
	if include_wave2b:
		enable_wave2b_voucher()
	else:
		enable_wave2a_analysis()
	settings = frappe.get_single("Iran Accounting Settings")
	settings.unified_party_enabled = 1
	settings.currency_analysis_enabled = 1
	for row in settings.account_explorer_party_sources or []:
		if row.party_type == "Customer":
			row.show_in_unified_party = 1
			if not row.identifier_field:
				row.identifier_field = "tax_id"
	settings.flags.ignore_permissions = True
	settings.save()
	frappe.db.commit()


def create_test_unified_accounting_party(
	members: list[tuple[str, str]],
	*,
	unified_name: str = "Test Unified Party",
	company: str | None = None,
) -> str:
	doc = frappe.new_doc("Unified Accounting Party")
	doc.unified_name = unified_name
	doc.status = "Active"
	if company:
		doc.company = company
	for index, (party_type, party) in enumerate(members):
		doc.append(
			"members",
			{
				"party_type": party_type,
				"party": party,
				"is_primary": 1 if index == 0 else 0,
				"sequence": index + 1,
			},
		)
	doc.flags.ignore_permissions = True
	doc.insert()
	frappe.db.commit()
	return doc.name


def delete_test_unified_accounting_party(name: str) -> None:
	if frappe.db.exists("Unified Accounting Party", name):
		frappe.delete_doc("Unified Accounting Party", name, force=1)
		frappe.db.commit()


def default_document_scope(company, fiscal_year, from_date, to_date) -> dict:
	return {
		"company": company,
		"fiscal_year": fiscal_year,
		"from_date": from_date,
		"to_date": to_date,
		"finance_book": None,
		"hide_zero_rows": 0,
		"voucher": {},
		"accounting": {},
		"accounting_dimensions": {},
		"currency": {"currency_type": "account_currency", "currency": None},
		"status": {
			"include_opening_entries": 1,
			"include_cancelled_entries": 0,
			"include_default_finance_book_entries": 1,
			"include_period_closing_vouchers": 0,
		},
	}


def build_payload(company, fiscal_year, from_date, to_date, analysis=None, document=None):
	document_scope = default_document_scope(company, fiscal_year, from_date, to_date)
	if document:
		for key, value in document.items():
			if isinstance(value, dict) and key in document_scope and isinstance(document_scope[key], dict):
				document_scope[key].update(value)
			else:
				document_scope[key] = value
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
