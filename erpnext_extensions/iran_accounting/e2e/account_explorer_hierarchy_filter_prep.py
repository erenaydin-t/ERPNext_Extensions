# Copyright (c) 2026, Farbod Siyahpoosh and contributors
"""Prep Account Explorer hierarchy for v4.6.3 presentation-level Playwright gates.

Targets the site Playwright actually serves (default site / restore-espad) using the
real Account Group 11 chart — matching the product bug report.
"""

from __future__ import annotations

import frappe

from erpnext_extensions.iran_accounting.tests.test_account_explorer_fixtures import (
	enable_account_explorer,
)


def prepare_hierarchy_filter_e2e(company: str | None = None) -> dict:
	frappe.connect()
	frappe.set_user("Administrator")
	enable_account_explorer()

	company = company or frappe.db.get_value("Company", {"abbr": "E"}, "name")
	if not company:
		company = frappe.db.get_value("Company", {}, "name", order_by="creation asc")
	if not company:
		frappe.throw("No company available for hierarchy filter e2e")

	group = frappe.db.get_value(
		"Account",
		{"company": company, "account_number": "11", "is_group": 1},
		"name",
	)
	if not group:
		frappe.throw(f"Account Group 11 not found for {company}")

	gl_rows = frappe.db.sql(
		"""
		select name, account_number
		from `tabAccount`
		where company = %s
			and is_group = 1
			and account_number is not null
			and char_length(account_number) = 4
			and account_number like '11%%'
		order by account_number
		limit 20
		""",
		company,
		as_dict=True,
	)
	gl_codes = [r.account_number for r in gl_rows]
	if len(gl_codes) < 2:
		frappe.throw("Need at least two GL children under Account Group 11")

	# Prefer dates that previously returned balances for Group 11 on this site.
	from_date, to_date = "2024-03-20", "2025-03-20"
	fy = frappe.db.sql(
		"""
		select fy.name
		from `tabFiscal Year` fy
		inner join `tabFiscal Year Company` fyc on fyc.parent = fy.name
		where fyc.company = %s and fy.disabled = 0
			and fy.year_start_date <= %s and fy.year_end_date >= %s
		order by fy.year_start_date desc
		limit 1
		""",
		(company, from_date, from_date),
	)
	fiscal_year = fy[0][0] if fy else None

	return {
		"company": company,
		"fiscal_year": fiscal_year,
		"from_date": from_date,
		"to_date": to_date,
		"group_account": group,
		"group_code": "11",
		"gl_codes": gl_codes,
		"sl_codes": [],  # SL codes vary; Group/GL assertions are the gate
		"expected_scoped_period_debit": None,
	}
