# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

import frappe
from erpnext.accounts.report.financial_statements import set_gl_entries_by_account
from erpnext.accounts.report.trial_balance.trial_balance import get_opening_balances
from frappe.query_builder.functions import Sum
from frappe.utils import flt

from erpnext_extensions.iran_accounting.account_explorer.filters import spec_to_trial_balance_filters
from erpnext_extensions.iran_accounting.account_explorer.gle_filters import (
	apply_opening_period_filters,
	apply_period_turnover_filters,
	apply_scoped_gle_filters,
	spec_has_advanced_gle_filters,
)
from erpnext_extensions.iran_accounting.account_explorer.measures import measures_from_opening_period
from erpnext_extensions.iran_accounting.account_explorer.party_opening import _toggle_debit_credit
from erpnext_extensions.iran_accounting.account_explorer.schemas import AccountExplorerQuerySpec


def get_account_wise_measures(
	spec: AccountExplorerQuerySpec, account_names: list[str] | None = None
) -> dict[str, dict]:
	"""Return per-account opening / period / closing measures.

	Hybrid strategy (Wave 3B-3A):

	1. **Unfiltered framing** (company, dates, finance book, PCV flags only):
	   Reuse ERPNext Trial Balance so Account Levels stay identical to
	   ``erpnext.accounts.report.trial_balance`` / ``set_gl_entries_by_account``.
	   That path may use Account Closing Balance shortcuts and cannot apply
	   party / voucher / currency / dimension / cancelled WHERE clauses.

	2. **Advanced analytical or document filters** (detected by
	   ``spec_has_advanced_gle_filters``): use the shared QuerySpec WHERE stack
	   ``apply_scoped_gle_filters`` — the same pipeline as party / dimension /
	   currency / voucher builders — so every Analysis Filter chip affects
	   accounting totals. Opening aggregates GL rows before ``from_date`` (plus
	   ``is_opening=Yes`` rows through ``to_date`` via
	   ``apply_opening_period_filters``, matching party/dimension helpers).
	   Period turnover is in-range and respects ``include_opening_entries`` via
	   ``apply_opening_entry_filters``. Cancelled / finance-book / PCV / party /
	   voucher / currency / dimension filters apply consistently on both queries.
	   No Account Closing Balance shortcuts are used on this path because those
	   aggregates ignore analytical filters.
	"""
	if spec_has_advanced_gle_filters(spec):
		return _get_account_wise_measures_scoped(spec, account_names)
	return _get_account_wise_measures_trial_balance(spec, account_names)


def _get_account_wise_measures_trial_balance(
	spec: AccountExplorerQuerySpec, account_names: list[str] | None = None
) -> dict[str, dict]:
	"""Unfiltered Account Levels — mirrors ERPNext Trial Balance.

	Preserved ERPNext paths:
	- ``erpnext.accounts.report.trial_balance.trial_balance.get_opening_balances``
	- ``erpnext.accounts.report.financial_statements.set_gl_entries_by_account``
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


def get_account_opening_balances(spec: AccountExplorerQuerySpec) -> dict[str, tuple[float, float]]:
	"""Filtered opening balances via scoped GL WHERE.

	Semantics (must match General Ledger under the same scope):
	- Rows with ``posting_date < from_date``, or opening entries with
	  ``is_opening = Yes`` and ``posting_date <= to_date`` (see
	  ``apply_opening_period_filters``).
	- Cancelled / finance-book / PCV / party / voucher / currency / dimensions
	  follow ``apply_scoped_gle_filters`` (Document Scope + Analysis scopes).
	- Debit/credit are netted to a single side after aggregation (Explorer
	  presentation), same as party/dimension opening helpers.
	"""
	gle = frappe.qb.DocType("GL Entry")
	query = frappe.qb.from_(gle).select(
		gle.account,
		Sum(gle.debit).as_("opening_debit"),
		Sum(gle.credit).as_("opening_credit"),
	)
	query = apply_scoped_gle_filters(query, gle, spec)
	query = apply_opening_period_filters(query, gle, spec)
	query = query.groupby(gle.account)

	return {
		row.account: _toggle_debit_credit(row.opening_debit, row.opening_credit)
		for row in query.run(as_dict=True)
		if row.account
	}


def get_account_period_balances(spec: AccountExplorerQuerySpec) -> dict[str, tuple[float, float]]:
	"""Filtered period turnover via scoped GL WHERE (one aggregate, GROUP BY account)."""
	gle = frappe.qb.DocType("GL Entry")
	query = frappe.qb.from_(gle).select(
		gle.account,
		Sum(gle.debit).as_("period_debit"),
		Sum(gle.credit).as_("period_credit"),
	)
	query = apply_scoped_gle_filters(query, gle, spec)
	query = apply_period_turnover_filters(query, gle, spec)
	query = query.groupby(gle.account)

	return {
		row.account: (flt(row.period_debit), flt(row.period_credit))
		for row in query.run(as_dict=True)
		if row.account
	}


def _get_account_wise_measures_scoped(
	spec: AccountExplorerQuerySpec, account_names: list[str] | None = None
) -> dict[str, dict]:
	# Exactly two aggregate queries (opening + period); no per-account N+1.
	opening = get_account_opening_balances(spec)
	period = get_account_period_balances(spec)

	if account_names is None:
		target_accounts = list({*opening.keys(), *period.keys()})
	else:
		target_accounts = list(account_names)

	result: dict[str, dict] = {}
	for account in target_accounts:
		opening_debit, opening_credit = opening.get(account, (0.0, 0.0))
		period_debit, period_credit = period.get(account, (0.0, 0.0))
		result[account] = measures_from_opening_period(
			opening_debit, opening_credit, period_debit, period_credit
		)
	return result


def get_accounts_with_direct_gl_postings(
	spec: AccountExplorerQuerySpec, group_account_names: set[str]
) -> set[str]:
	if not group_account_names:
		return set()

	gle = frappe.qb.DocType("GL Entry")
	query = frappe.qb.from_(gle).select(gle.account).distinct()
	query = apply_scoped_gle_filters(query, gle, spec)
	query = apply_period_turnover_filters(query, gle, spec)
	query = query.where(gle.account.isin(list(group_account_names)))

	return {row.account for row in query.run(as_dict=True) if row.account}
