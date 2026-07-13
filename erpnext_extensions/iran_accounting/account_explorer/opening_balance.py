# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

import frappe
from erpnext.accounts.report.financial_statements import set_gl_entries_by_account
from erpnext.accounts.report.trial_balance.trial_balance import get_opening_balances
from frappe.utils import flt

from erpnext_extensions.iran_accounting.account_explorer.filters import spec_to_trial_balance_filters
from erpnext_extensions.iran_accounting.account_explorer.measures import measures_from_opening_period
from erpnext_extensions.iran_accounting.account_explorer.schemas import AccountExplorerQuerySpec


def get_account_wise_measures(
	spec: AccountExplorerQuerySpec, account_names: list[str] | None = None
) -> dict[str, dict]:
	"""Return per-account measures aligned with ERPNext Trial Balance.

	Mirrors:
	- erpnext.accounts.report.trial_balance.trial_balance.get_opening_balances
	- erpnext.accounts.report.financial_statements.set_gl_entries_by_account
	- erpnext.accounts.report.trial_balance.trial_balance.calculate_values
	"""
	filters = spec_to_trial_balance_filters(spec)
	ignore_is_opening = frappe.get_single_value("Accounts Settings", "ignore_is_opening_check_for_reporting")
	opening_balances = get_opening_balances(filters, ignore_is_opening)

	gl_entries_by_account: dict[str, list] = {}
	set_gl_entries_by_account(
		spec.company,
		spec.from_date,
		spec.to_date,
		filters,
		gl_entries_by_account,
		ignore_closing_entries=not spec.include_period_closing_vouchers,
		ignore_opening_entries=True,
		group_by_account=True,
	)

	target_accounts = account_names
	if target_accounts is None:
		target_accounts = list({*opening_balances.keys(), *gl_entries_by_account.keys()})

	result: dict[str, dict] = {}
	for account in target_accounts:
		opening = opening_balances.get(account, {})
		opening_debit = flt(opening.get("opening_debit"))
		opening_credit = flt(opening.get("opening_credit"))
		period_debit = 0.0
		period_credit = 0.0
		for entry in gl_entries_by_account.get(account, []):
			period_debit += flt(entry.debit)
			period_credit += flt(entry.credit)
		result[account] = measures_from_opening_period(
			opening_debit, opening_credit, period_debit, period_credit
		)
	return result


def get_accounts_with_direct_gl_postings(
	spec: AccountExplorerQuerySpec, group_account_names: set[str]
) -> set[str]:
	if not group_account_names:
		return set()
	names = tuple(group_account_names)
	rows = frappe.db.sql(
		"""
		select distinct gle.account
		from `tabGL Entry` gle
		where gle.company = %s
		  and gle.is_cancelled = 0
		  and gle.posting_date between %s and %s
		  and gle.account in %s
		""",
		(spec.company, spec.from_date, spec.to_date, names),
		as_dict=True,
	)
	return {row.account for row in rows}
