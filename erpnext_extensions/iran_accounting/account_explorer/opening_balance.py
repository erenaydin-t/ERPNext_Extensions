# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

import frappe
from erpnext.accounts.report.financial_statements import set_gl_entries_by_account
from erpnext.accounts.report.trial_balance.trial_balance import get_opening_balances
from frappe.query_builder.functions import Sum
from frappe.utils import flt

from erpnext_extensions.iran_accounting.account_explorer.filters import spec_to_trial_balance_filters
from erpnext_extensions.iran_accounting.account_explorer.gle_filters import (
	apply_period_turnover_filters,
	apply_scoped_gle_filters,
)
from erpnext_extensions.iran_accounting.account_explorer.measures import measures_from_opening_period
from erpnext_extensions.iran_accounting.account_explorer.opening_entry_policy import (
	AccountAxisEngine,
	OpeningEntryPolicyMode,
	adjust_tb_opening_for_policy,
	aggregate_opening_flagged_by_account,
	apply_policy_opening_filters,
	apply_policy_turnover_filters,
	policy_from_spec,
	select_account_axis_engine,
	site_ignore_is_opening,
)
from erpnext_extensions.iran_accounting.account_explorer.party_opening import _toggle_debit_credit
from erpnext_extensions.iran_accounting.account_explorer.schemas import AccountExplorerQuerySpec


def get_account_wise_measures(
	spec: AccountExplorerQuerySpec, account_names: list[str] | None = None
) -> dict[str, dict]:
	"""Return per-account opening / period / closing measures.

	Engine selection (v4.5.0 OpeningEntryPolicy):

	- **E1** — ERPNext Trial Balance + ``is_opening='Yes'`` pre-period delta.
	- **E2** — E1 + gap-window opening-flagged supplement (ON + PCV/ACB).
	- **E3** — Scoped policy GL (advanced filters or OFF+ACB correctness fallback).
	"""
	engine = select_account_axis_engine(spec)
	if engine == AccountAxisEngine.E3_SCOPED_GL:
		return _get_account_wise_measures_scoped(spec, account_names)
	if engine == AccountAxisEngine.E2_TB_GAP_SUPPLEMENT:
		return _get_account_wise_measures_e2(spec, account_names)
	return _get_account_wise_measures_e1(spec, account_names)


def _get_account_wise_measures_e1(
	spec: AccountExplorerQuerySpec, account_names: list[str] | None = None
) -> dict[str, dict]:
	"""E1 — TB baseline + pre-period opening-flagged delta."""
	filters = spec_to_trial_balance_filters(spec)
	policy = policy_from_spec(spec)
	ignore_is_opening = site_ignore_is_opening()
	opening_balances = get_opening_balances(filters, ignore_is_opening)
	aux_pre = aggregate_opening_flagged_by_account(spec, bucket="pre")
	aux_in = aggregate_opening_flagged_by_account(spec, bucket="in")

	gl_entries_by_account: dict[str, list] = {}
	# Always batch-fetch period GL (group_by_account=True). Policy OFF excludes
	# is_opening='Yes' turnover via aux_in subtraction — not ERPNext
	# ignore_opening_entries=True, which triggers per-account query explosion.
	set_gl_entries_by_account(
		spec.company,
		spec.from_date,
		spec.to_date,
		filters,
		gl_entries_by_account,
		ignore_closing_entries=not spec.include_period_closing_vouchers,
		ignore_opening_entries=False,
		group_by_account=True,
	)

	target_accounts = account_names
	if target_accounts is None:
		target_accounts = list({*opening_balances.keys(), *gl_entries_by_account.keys(), *aux_pre.keys()})

	result: dict[str, dict] = {}
	for account in target_accounts:
		opening = opening_balances.get(account, {})
		aux_debit, aux_credit = aux_pre.get(account, (0.0, 0.0))
		in_debit, in_credit = aux_in.get(account, (0.0, 0.0)) if aux_in else (0.0, 0.0)
		opening_debit, opening_credit = adjust_tb_opening_for_policy(
			flt(opening.get("opening_debit")),
			flt(opening.get("opening_credit")),
			aux_debit,
			aux_credit,
			policy,
		)
		if aux_in:
			opening_debit = flt(opening_debit) - flt(in_debit)
			opening_credit = flt(opening_credit) - flt(in_credit)
		period_debit = 0.0
		period_credit = 0.0
		for entry in gl_entries_by_account.get(account, []):
			period_debit += flt(entry.debit)
			period_credit += flt(entry.credit)
		if policy == OpeningEntryPolicyMode.EXCLUDE_OPENING_FLAGGED:
			period_debit = flt(period_debit) - flt(in_debit)
			period_credit = flt(period_credit) - flt(in_credit)
		result[account] = measures_from_opening_period(
			opening_debit, opening_credit, period_debit, period_credit
		)
	return result


def _get_account_wise_measures_e2(
	spec: AccountExplorerQuerySpec, account_names: list[str] | None = None
) -> dict[str, dict]:
	"""E2 — E1 + gap-window opening-flagged supplement to opening bucket."""
	result = _get_account_wise_measures_e1(spec, account_names)
	aux_gap = aggregate_opening_flagged_by_account(spec, bucket="gap")
	if not aux_gap:
		return result

	target_accounts = account_names if account_names is not None else list(result.keys())
	for account in target_accounts:
		if account not in result:
			continue
		gap_debit, gap_credit = aux_gap.get(account, (0.0, 0.0))
		if not gap_debit and not gap_credit:
			continue
		row = result[account]
		result[account] = measures_from_opening_period(
			flt(row["opening_debit"]) + flt(gap_debit),
			flt(row["opening_credit"]) + flt(gap_credit),
			flt(row["period_debit"]),
			flt(row["period_credit"]),
		)
	return result


def get_account_opening_balances(spec: AccountExplorerQuerySpec) -> dict[str, tuple[float, float]]:
	"""Filtered opening balances via scoped policy GL WHERE."""
	gle = frappe.qb.DocType("GL Entry")
	query = frappe.qb.from_(gle).select(
		gle.account,
		Sum(gle.debit).as_("opening_debit"),
		Sum(gle.credit).as_("opening_credit"),
	)
	query = apply_scoped_gle_filters(query, gle, spec)
	query = apply_policy_opening_filters(query, gle, spec)
	query = query.groupby(gle.account)

	return {
		row.account: _toggle_debit_credit(row.opening_debit, row.opening_credit)
		for row in query.run(as_dict=True)
		if row.account
	}


def get_account_period_balances(spec: AccountExplorerQuerySpec) -> dict[str, tuple[float, float]]:
	"""Filtered period turnover via scoped policy GL WHERE."""
	gle = frappe.qb.DocType("GL Entry")
	query = frappe.qb.from_(gle).select(
		gle.account,
		Sum(gle.debit).as_("period_debit"),
		Sum(gle.credit).as_("period_credit"),
	)
	query = apply_scoped_gle_filters(query, gle, spec)
	query = apply_policy_turnover_filters(query, gle, spec)
	query = query.groupby(gle.account)

	return {
		row.account: (flt(row.period_debit), flt(row.period_credit))
		for row in query.run(as_dict=True)
		if row.account
	}


def _get_account_wise_measures_scoped(
	spec: AccountExplorerQuerySpec, account_names: list[str] | None = None
) -> dict[str, dict]:
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
