# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

import frappe

from erpnext_extensions.iran_accounting.account_explorer.schemas import AccountExplorerQuerySpec


def spec_to_trial_balance_filters(spec: AccountExplorerQuerySpec):
	"""Build a frappe._dict compatible with ERPNext Trial Balance / financial_statements."""
	filters = frappe._dict(
		company=spec.company,
		from_date=spec.from_date,
		to_date=spec.to_date,
		fiscal_year=spec.fiscal_year,
		finance_book=spec.finance_book,
		include_default_book_entries=1 if spec.include_default_book_entries else 0,
		with_period_closing_entry_for_current_period=1 if spec.include_period_closing_vouchers else 0,
		with_period_closing_entry_for_opening=1 if spec.include_period_closing_vouchers else 0,
		show_zero_values=0 if spec.hide_zero_rows else 1,
		show_unclosed_fy_pl_balances=1,
	)
	if spec.fiscal_year:
		fy = frappe.get_cached_value(
			"Fiscal Year",
			spec.fiscal_year,
			["year_start_date", "year_end_date"],
			as_dict=True,
		)
		if fy:
			filters.year_start_date = fy.year_start_date
			filters.year_end_date = fy.year_end_date
	if spec.finance_book:
		filters.company_fb = frappe.get_cached_value("Company", spec.company, "default_finance_book")
	return filters
