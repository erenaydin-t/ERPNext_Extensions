# Copyright (c) 2026, Farbod Siyahpoosh and contributors
"""Opening-entry policy layer for Account Explorer v4.5.0.

Centralises is_opening bucket semantics, account-axis engine selection, and
deterministic row classification. Axis builders consume this module in Phase 2+.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

import frappe
from frappe.utils import add_days, cint, flt, getdate

from erpnext_extensions.iran_accounting.account_explorer.gle_filters import spec_has_advanced_gle_filters
from erpnext_extensions.iran_accounting.account_explorer.measures import measures_from_opening_period
from erpnext_extensions.iran_accounting.account_explorer.schemas import AccountExplorerQuerySpec

OPENING_FLAGGED_VALUE = "Yes"


class OpeningEntryPolicyMode(str, Enum):
	EXCLUDE_OPENING_FLAGGED = "exclude_opening_flagged"
	INCLUDE_OPENING_FLAGGED = "include_opening_flagged"


class AccountAxisEngine(str, Enum):
	E1_TB_DELTA = "E1"
	E2_TB_GAP_SUPPLEMENT = "E2"
	E3_SCOPED_GL = "E3"


class RowTiming(str, Enum):
	BEFORE_PERIOD = "before_period"
	ON_FROM_DATE = "on_from_date"
	IN_PERIOD = "in_period"
	ON_TO_DATE = "on_to_date"
	AFTER_PERIOD = "after_period"


@dataclass(frozen=True)
class PeriodWindow:
	from_date: Any
	to_date: Any

	def normalized(self) -> tuple[Any, Any]:
		return getdate(self.from_date), getdate(self.to_date)


def policy_from_include_opening_entries(include_opening_entries: bool) -> OpeningEntryPolicyMode:
	if include_opening_entries:
		return OpeningEntryPolicyMode.INCLUDE_OPENING_FLAGGED
	return OpeningEntryPolicyMode.EXCLUDE_OPENING_FLAGGED


def policy_from_spec(spec: AccountExplorerQuerySpec) -> OpeningEntryPolicyMode:
	return policy_from_include_opening_entries(spec.include_opening_entries)


def site_ignore_is_opening() -> bool:
	return bool(
		cint(frappe.get_single_value("Accounts Settings", "ignore_is_opening_check_for_reporting"))
	)


def row_timing(posting_date: Any, window: PeriodWindow) -> RowTiming:
	posting = getdate(posting_date)
	from_date, to_date = window.normalized()
	if posting < from_date:
		return RowTiming.BEFORE_PERIOD
	if posting == from_date:
		return RowTiming.ON_FROM_DATE
	if posting == to_date:
		return RowTiming.ON_TO_DATE if from_date != to_date else RowTiming.ON_FROM_DATE
	if posting > to_date:
		return RowTiming.AFTER_PERIOD
	return RowTiming.IN_PERIOD


def _is_opening_flagged(value: Any) -> bool:
	return cstr_is_opening(value) == OPENING_FLAGGED_VALUE


def cstr_is_opening(value: Any) -> str:
	return cstr(value or "No")


def row_is_eligible_base(row: dict) -> bool:
	"""Apply non-policy scope gates used by golden fixtures (cancelled / PCV)."""
	if cint(row.get("is_cancelled")):
		return False
	if cstr(row.get("voucher_type")) == "Period Closing Voucher":
		return False
	return True


def row_contributes_opening(
	row: dict,
	policy: OpeningEntryPolicyMode,
	window: PeriodWindow,
	*,
	include_cancelled: bool = False,
	include_pcv: bool = False,
) -> bool:
	if not include_cancelled and cint(row.get("is_cancelled")):
		return False
	if not include_pcv and cstr(row.get("voucher_type")) == "Period Closing Voucher":
		return False

	timing = row_timing(row.get("posting_date"), window)
	if timing in (RowTiming.AFTER_PERIOD,):
		return False

	opening_flagged = _is_opening_flagged(row.get("is_opening"))
	if policy == OpeningEntryPolicyMode.EXCLUDE_OPENING_FLAGGED:
		return timing == RowTiming.BEFORE_PERIOD and not opening_flagged
	# INCLUDE: pre-period normal + pre-period opening; never in-period opening.
	return timing == RowTiming.BEFORE_PERIOD


def row_contributes_turnover(
	row: dict,
	policy: OpeningEntryPolicyMode,
	window: PeriodWindow,
	*,
	include_cancelled: bool = False,
	include_pcv: bool = False,
) -> bool:
	if not include_cancelled and cint(row.get("is_cancelled")):
		return False
	if not include_pcv and cstr(row.get("voucher_type")) == "Period Closing Voucher":
		return False

	timing = row_timing(row.get("posting_date"), window)
	if timing not in (RowTiming.ON_FROM_DATE, RowTiming.IN_PERIOD, RowTiming.ON_TO_DATE):
		return False

	opening_flagged = _is_opening_flagged(row.get("is_opening"))
	if policy == OpeningEntryPolicyMode.EXCLUDE_OPENING_FLAGGED:
		return not opening_flagged
	return True


def aggregate_measures_from_rows(
	rows: list[dict],
	policy: OpeningEntryPolicyMode,
	window: PeriodWindow,
	*,
	include_cancelled: bool = False,
	include_pcv: bool = False,
) -> dict[str, float]:
	opening_debit = opening_credit = period_debit = period_credit = 0.0
	for row in rows:
		debit = flt(row.get("debit"))
		credit = flt(row.get("credit"))
		if row_contributes_opening(
			row, policy, window, include_cancelled=include_cancelled, include_pcv=include_pcv
		):
			opening_debit += debit
			opening_credit += credit
		if row_contributes_turnover(
			row, policy, window, include_cancelled=include_cancelled, include_pcv=include_pcv
		):
			period_debit += debit
			period_credit += credit
	return measures_from_opening_period(opening_debit, opening_credit, period_debit, period_credit)


def opening_flagged_contribution(
	rows: list[dict],
	policy: OpeningEntryPolicyMode,
	window: PeriodWindow,
) -> dict[str, float]:
	"""Net contribution of is_opening=Yes rows to reported opening+period buckets."""
	opening_net = period_net = 0.0
	for row in rows:
		if not _is_opening_flagged(row.get("is_opening")):
			continue
		debit = flt(row.get("debit"))
		credit = flt(row.get("credit"))
		if row_contributes_opening(row, policy, window):
			opening_net += debit - credit
		if row_contributes_turnover(row, policy, window):
			period_net += debit - credit
	return {"opening_net": opening_net, "period_net": period_net}


def assert_closing_invariant(measures: dict[str, float], *, tolerance: float = 1e-9) -> None:
	opening_net = flt(measures.get("opening_debit")) - flt(measures.get("opening_credit"))
	period_net = flt(measures.get("period_debit")) - flt(measures.get("period_credit"))
	closing_net = flt(measures.get("net_balance"))
	if abs((opening_net + period_net) - closing_net) > tolerance:
		raise AssertionError(
			f"closing invariant failed: opening_net={opening_net} period_net={period_net} "
			f"expected={opening_net + period_net} actual net_balance={closing_net}"
		)


def assert_off_zero_opening_flagged(
	rows: list[dict],
	measures: dict[str, float],
	window: PeriodWindow,
	*,
	tolerance: float = 1e-9,
) -> None:
	contrib = opening_flagged_contribution(rows, OpeningEntryPolicyMode.EXCLUDE_OPENING_FLAGGED, window)
	if abs(contrib["opening_net"]) > tolerance or abs(contrib["period_net"]) > tolerance:
		raise AssertionError(
			f"OFF policy requires zero opening-flagged contribution; got {contrib}"
		)


def assert_on_partition(
	rows: list[dict],
	measures: dict[str, float],
	window: PeriodWindow,
	*,
	tolerance: float = 1e-9,
) -> None:
	policy = OpeningEntryPolicyMode.INCLUDE_OPENING_FLAGGED
	for row in rows:
		if not _is_opening_flagged(row.get("is_opening")):
			continue
		in_opening = row_contributes_opening(row, policy, window)
		in_turnover = row_contributes_turnover(row, policy, window)
		if in_opening and in_turnover:
			raise AssertionError(f"opening row in both buckets: {row}")
		timing = row_timing(row.get("posting_date"), window)
		if timing == RowTiming.BEFORE_PERIOD and not in_opening:
			raise AssertionError(f"pre-period opening row missing from opening: {row}")
		if timing in (RowTiming.ON_FROM_DATE, RowTiming.IN_PERIOD, RowTiming.ON_TO_DATE) and not in_turnover:
			raise AssertionError(f"in-period opening row missing from turnover: {row}")


def apply_policy_opening_filters(query, gle, spec: AccountExplorerQuerySpec):
	"""PyPika WHERE for opening bucket (E3 scoped path)."""
	policy = policy_from_spec(spec)
	from_date, _to_date = getdate(spec.from_date), getdate(spec.to_date)
	query = query.where(gle.posting_date < from_date)
	if policy == OpeningEntryPolicyMode.EXCLUDE_OPENING_FLAGGED:
		query = query.where(gle.is_opening == "No")
	return query


def apply_policy_turnover_filters(query, gle, spec: AccountExplorerQuerySpec):
	"""PyPika WHERE for turnover bucket (E3 scoped path)."""
	policy = policy_from_spec(spec)
	from_date, to_date = getdate(spec.from_date), getdate(spec.to_date)
	query = query.where(gle.posting_date >= from_date).where(gle.posting_date <= to_date)
	if policy == OpeningEntryPolicyMode.EXCLUDE_OPENING_FLAGGED:
		query = query.where(gle.is_opening == "No")
	return query


def last_pcv_before_from_date(spec: AccountExplorerQuerySpec) -> dict | None:
	cache = _policy_request_cache(spec)
	if "pcv" not in cache:
		cache["pcv"] = _fetch_last_pcv_before_from_date(spec)
	return cache["pcv"]


def _fetch_last_pcv_before_from_date(spec: AccountExplorerQuerySpec) -> dict | None:
	if not spec.from_date:
		return None
	rows = frappe.get_all(
		"Period Closing Voucher",
		filters={
			"docstatus": 1,
			"company": spec.company,
			"period_end_date": ("<", getdate(spec.from_date)),
		},
		fields=["name", "period_end_date"],
		order_by="period_end_date desc",
		limit=1,
	)
	return rows[0] if rows else None


def _policy_request_cache(spec: AccountExplorerQuerySpec) -> dict:
	key = (spec.company, str(getdate(spec.from_date) if spec.from_date else ""))
	store = getattr(frappe.local, "_ae_opening_policy_cache", None)
	if store is None:
		store = {}
		frappe.local._ae_opening_policy_cache = store
	if key not in store:
		store[key] = {}
	return store[key]


def acb_applicable(spec: AccountExplorerQuerySpec) -> bool:
	cache = _policy_request_cache(spec)
	if "acb_applicable" not in cache:
		if cint(frappe.get_single_value("Accounts Settings", "ignore_account_closing_balance")):
			cache["acb_applicable"] = False
		else:
			cache["acb_applicable"] = last_pcv_before_from_date(spec) is not None
	return cache["acb_applicable"]


def opening_flagged_baked_in_acb(spec: AccountExplorerQuerySpec) -> bool:
	cache = _policy_request_cache(spec)
	if "opening_flagged_baked" not in cache:
		pcv = last_pcv_before_from_date(spec)
		if not pcv:
			cache["opening_flagged_baked"] = False
		else:
			cache["opening_flagged_baked"] = bool(
				frappe.db.exists(
					"GL Entry",
					{
						"company": spec.company,
						"is_cancelled": 0,
						"is_opening": OPENING_FLAGGED_VALUE,
						"posting_date": ("<=", getdate(pcv.period_end_date)),
					},
				)
			)
	return cache["opening_flagged_baked"]


def select_account_axis_engine(spec: AccountExplorerQuerySpec) -> AccountAxisEngine:
	if spec_has_advanced_gle_filters(spec):
		return AccountAxisEngine.E3_SCOPED_GL

	policy = policy_from_spec(spec)
	if policy == OpeningEntryPolicyMode.EXCLUDE_OPENING_FLAGGED and acb_applicable(spec):
		if opening_flagged_baked_in_acb(spec):
			return AccountAxisEngine.E3_SCOPED_GL

	if (
		policy == OpeningEntryPolicyMode.INCLUDE_OPENING_FLAGGED
		and acb_applicable(spec)
		and not site_ignore_is_opening()
	):
		return AccountAxisEngine.E2_TB_GAP_SUPPLEMENT

	return AccountAxisEngine.E1_TB_DELTA


def gap_window_for_spec(spec: AccountExplorerQuerySpec) -> tuple[Any, Any] | None:
	pcv = last_pcv_before_from_date(spec)
	if not pcv:
		return None
	gap_start = add_days(getdate(pcv.period_end_date), 1)
	gap_end = add_days(getdate(spec.from_date), -1)
	if gap_start > gap_end:
		return None
	return gap_start, gap_end


def aggregate_opening_flagged_by_account(
	spec: AccountExplorerQuerySpec,
	*,
	bucket: str,
) -> dict[str, tuple[float, float]]:
	"""TB-compatible auxiliary aggregates for is_opening='Yes' rows (E1/E2 deltas).

	bucket: ``pre`` (before from_date), ``in`` (in period), ``gap`` (PCV gap window).
	"""
	from frappe.query_builder.functions import Sum

	from erpnext_extensions.iran_accounting.account_explorer import e1_gl_scope
	from erpnext_extensions.iran_accounting.account_explorer.gle_filters import (
		apply_document_scope_filters,
	)

	gle = frappe.qb.DocType("GL Entry")
	query = frappe.qb.from_(gle).select(
		gle.account,
		Sum(gle.debit).as_("debit"),
		Sum(gle.credit).as_("credit"),
	)
	query = apply_document_scope_filters(query, gle, spec)
	query = query.where(gle.is_opening == OPENING_FLAGGED_VALUE)
	if narrowed := e1_gl_scope.resolve_narrowed_gl_accounts(spec):
		query = query.where(gle.account.isin(narrowed))

	from_date, to_date = getdate(spec.from_date), getdate(spec.to_date)
	if bucket == "pre":
		query = query.where(gle.posting_date < from_date)
	elif bucket == "in":
		query = query.where(gle.posting_date >= from_date).where(gle.posting_date <= to_date)
	elif bucket == "gap":
		gap = gap_window_for_spec(spec)
		if not gap:
			return {}
		gap_start, gap_end = gap
		query = query.where(gle.posting_date >= gap_start).where(gle.posting_date <= gap_end)
	else:
		raise ValueError(f"unsupported opening-flagged bucket: {bucket}")

	query = query.groupby(gle.account)
	return {
		row.account: (flt(row.debit), flt(row.credit))
		for row in query.run(as_dict=True)
		if row.account
	}


def aggregate_opening_flagged_pre_in_by_account(
	spec: AccountExplorerQuerySpec,
) -> tuple[dict[str, tuple[float, float]], dict[str, tuple[float, float]]]:
	"""Single-scan pre-period and in-period opening-flagged aggregates (E1 hot path)."""
	from frappe.query_builder.functions import Sum

	from erpnext_extensions.iran_accounting.account_explorer import e1_gl_scope
	from erpnext_extensions.iran_accounting.account_explorer.gle_filters import (
		apply_document_scope_filters,
	)

	gle = frappe.qb.DocType("GL Entry")
	from_date, to_date = getdate(spec.from_date), getdate(spec.to_date)
	pre_cond = gle.posting_date < from_date
	in_cond = (gle.posting_date >= from_date) & (gle.posting_date <= to_date)
	case = frappe.qb.terms.Case

	query = (
		frappe.qb.from_(gle)
		.select(
			gle.account,
			Sum(case().when(pre_cond, gle.debit).else_(0)).as_("pre_debit"),
			Sum(case().when(pre_cond, gle.credit).else_(0)).as_("pre_credit"),
			Sum(case().when(in_cond, gle.debit).else_(0)).as_("in_debit"),
			Sum(case().when(in_cond, gle.credit).else_(0)).as_("in_credit"),
		)
		.where(gle.is_opening == OPENING_FLAGGED_VALUE)
		.where(pre_cond | in_cond)
		.groupby(gle.account)
	)
	query = apply_document_scope_filters(query, gle, spec)
	if narrowed := e1_gl_scope.resolve_narrowed_gl_accounts(spec):
		query = query.where(gle.account.isin(narrowed))

	pre: dict[str, tuple[float, float]] = {}
	in_period: dict[str, tuple[float, float]] = {}
	for row in query.run(as_dict=True):
		if not row.account:
			continue
		pre_debit, pre_credit = flt(row.pre_debit), flt(row.pre_credit)
		in_debit, in_credit = flt(row.in_debit), flt(row.in_credit)
		if pre_debit or pre_credit:
			pre[row.account] = (pre_debit, pre_credit)
		if in_debit or in_credit:
			in_period[row.account] = (in_debit, in_credit)
	return pre, in_period


def adjust_tb_opening_for_policy(
	tb_opening_debit: float,
	tb_opening_credit: float,
	aux_pre_debit: float,
	aux_pre_credit: float,
	policy: OpeningEntryPolicyMode,
) -> tuple[float, float]:
	"""Reconcile TB opening with OpeningEntryPolicy semantics via aux_pre delta."""
	site_ignore = site_ignore_is_opening()
	if policy == OpeningEntryPolicyMode.EXCLUDE_OPENING_FLAGGED:
		if not site_ignore:
			return flt(tb_opening_debit) - flt(aux_pre_debit), flt(tb_opening_credit) - flt(aux_pre_credit)
		return flt(tb_opening_debit), flt(tb_opening_credit)
	if site_ignore:
		return flt(tb_opening_debit) + flt(aux_pre_debit), flt(tb_opening_credit) + flt(aux_pre_credit)
	return flt(tb_opening_debit), flt(tb_opening_credit)


def cstr(value: Any) -> str:
	from frappe.utils import cstr as frappe_cstr

	return frappe_cstr(value)
