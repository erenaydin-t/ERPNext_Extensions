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


def acb_applicable(spec: AccountExplorerQuerySpec) -> bool:
	if cint(frappe.get_single_value("Accounts Settings", "ignore_account_closing_balance")):
		return False
	return last_pcv_before_from_date(spec) is not None


def opening_flagged_baked_in_acb(spec: AccountExplorerQuerySpec) -> bool:
	pcv = last_pcv_before_from_date(spec)
	if not pcv:
		return False
	return bool(
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


def cstr(value: Any) -> str:
	from frappe.utils import cstr as frappe_cstr

	return frappe_cstr(value)
