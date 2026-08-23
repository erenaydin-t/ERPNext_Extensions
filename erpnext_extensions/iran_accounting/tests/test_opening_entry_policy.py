# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

import unittest
from datetime import date
from unittest.mock import patch

from erpnext_extensions.iran_accounting.account_explorer.measures import finalize_measures
from erpnext_extensions.iran_accounting.account_explorer.opening_entry_policy import (
	AccountAxisEngine,
	OpeningEntryPolicyMode,
	PeriodWindow,
	RowTiming,
	aggregate_measures_from_rows,
	assert_closing_invariant,
	assert_off_zero_opening_flagged,
	assert_on_partition,
	policy_from_include_opening_entries,
	row_contributes_opening,
	row_contributes_turnover,
	row_timing,
	select_account_axis_engine,
)
from erpnext_extensions.iran_accounting.account_explorer.schemas import (
	AccountExplorerQuerySpec,
	AccountingFilter,
	AnalysisContext,
	DocumentScope,
	StatusFilter,
)
from erpnext_extensions.iran_accounting.tests.opening_policy_golden_fixtures import FROM_DATE, TO_DATE


def _row(
	posting_date: date,
	*,
	debit: float = 0.0,
	credit: float = 0.0,
	is_opening: str = "No",
	is_cancelled: int = 0,
	voucher_type: str = "Journal Entry",
	finance_book: str = "",
) -> dict:
	return {
		"posting_date": posting_date,
		"debit": debit,
		"credit": credit,
		"is_opening": is_opening,
		"is_cancelled": is_cancelled,
		"voucher_type": voucher_type,
		"finance_book": finance_book,
	}


def _spec(
	*,
	include_opening_entries: bool = True,
	company: str = "_Test Company",
	from_date=FROM_DATE,
	to_date=TO_DATE,
	accounting: AccountingFilter | None = None,
) -> AccountExplorerQuerySpec:
	return AccountExplorerQuerySpec(
		document_scope=DocumentScope(
			company=company,
			from_date=from_date,
			to_date=to_date,
			status=StatusFilter(include_opening_entries=include_opening_entries),
			accounting=accounting or AccountingFilter(),
		),
		analysis=AnalysisContext(view_axis="account_level"),
	)


class TestOpeningEntryPolicyMode(unittest.TestCase):
	def test_policy_from_include_opening_entries(self):
		self.assertEqual(
			policy_from_include_opening_entries(False),
			OpeningEntryPolicyMode.EXCLUDE_OPENING_FLAGGED,
		)
		self.assertEqual(
			policy_from_include_opening_entries(True),
			OpeningEntryPolicyMode.INCLUDE_OPENING_FLAGGED,
		)


class TestRowTiming(unittest.TestCase):
	def setUp(self):
		self.window = PeriodWindow(FROM_DATE, TO_DATE)

	def test_date_matrix(self):
		cases = [
			(date(2026, 3, 31), RowTiming.BEFORE_PERIOD),
			(FROM_DATE, RowTiming.ON_FROM_DATE),
			(date(2026, 4, 15), RowTiming.IN_PERIOD),
			(TO_DATE, RowTiming.ON_TO_DATE),
			(date(2026, 5, 1), RowTiming.AFTER_PERIOD),
		]
		for posting_date, expected in cases:
			with self.subTest(posting_date=posting_date):
				self.assertEqual(row_timing(posting_date, self.window), expected)

	def test_same_day_window_uses_on_from_date(self):
		window = PeriodWindow(date(2026, 4, 1), date(2026, 4, 1))
		self.assertEqual(row_timing(date(2026, 4, 1), window), RowTiming.ON_FROM_DATE)


class TestBucketPredicates(unittest.TestCase):
	def setUp(self):
		self.window = PeriodWindow(FROM_DATE, TO_DATE)

	def test_off_excludes_opening_flagged_everywhere(self):
		rows = [
			_row(date(2026, 3, 1), debit=100, is_opening="Yes"),
			_row(FROM_DATE, debit=200, is_opening="Yes"),
			_row(date(2026, 4, 10), debit=300, is_opening="Yes"),
		]
		policy = OpeningEntryPolicyMode.EXCLUDE_OPENING_FLAGGED
		for row in rows:
			self.assertFalse(row_contributes_opening(row, policy, self.window))
			self.assertFalse(row_contributes_turnover(row, policy, self.window))

	def test_on_partitions_opening_rows(self):
		policy = OpeningEntryPolicyMode.INCLUDE_OPENING_FLAGGED
		pre = _row(date(2026, 3, 1), debit=100, is_opening="Yes")
		in_period = _row(date(2026, 4, 10), debit=200, is_opening="Yes")
		self.assertTrue(row_contributes_opening(pre, policy, self.window))
		self.assertFalse(row_contributes_turnover(pre, policy, self.window))
		self.assertFalse(row_contributes_opening(in_period, policy, self.window))
		self.assertTrue(row_contributes_turnover(in_period, policy, self.window))

	def test_normal_pre_period_stays_in_opening_under_both_policies(self):
		row = _row(date(2026, 3, 1), debit=500)
		for policy in OpeningEntryPolicyMode:
			self.assertTrue(row_contributes_opening(row, policy, self.window))
			self.assertFalse(row_contributes_turnover(row, policy, self.window))

	def test_cancelled_and_pcv_excluded_by_default(self):
		cancelled = _row(date(2026, 4, 5), debit=100, is_cancelled=1)
		pcv = _row(date(2026, 4, 5), debit=100, voucher_type="Period Closing Voucher")
		policy = OpeningEntryPolicyMode.INCLUDE_OPENING_FLAGGED
		for row in (cancelled, pcv):
			self.assertFalse(row_contributes_opening(row, policy, self.window))
			self.assertFalse(row_contributes_turnover(row, policy, self.window))

	def test_after_period_excluded(self):
		row = _row(date(2026, 5, 1), debit=100)
		for policy in OpeningEntryPolicyMode:
			self.assertFalse(row_contributes_opening(row, policy, self.window))
			self.assertFalse(row_contributes_turnover(row, policy, self.window))


class TestAggregateMeasures(unittest.TestCase):
	def setUp(self):
		self.window = PeriodWindow(FROM_DATE, TO_DATE)

	def test_off_normal_pre_period_in_opening_only(self):
		rows = [_row(date(2026, 3, 1), debit=800)]
		measures = aggregate_measures_from_rows(rows, OpeningEntryPolicyMode.EXCLUDE_OPENING_FLAGGED, self.window)
		self.assertEqual(measures["opening_debit"], 800)
		self.assertEqual(measures["period_debit"], 0)

	def test_on_in_period_opening_in_turnover_only(self):
		rows = [_row(date(2026, 4, 10), debit=300, is_opening="Yes")]
		measures = aggregate_measures_from_rows(rows, OpeningEntryPolicyMode.INCLUDE_OPENING_FLAGGED, self.window)
		self.assertEqual(measures["opening_debit"], 0)
		self.assertEqual(measures["period_debit"], 300)


class TestAccountingInvariants(unittest.TestCase):
	def setUp(self):
		self.window = PeriodWindow(FROM_DATE, TO_DATE)

	def _assert_fixture_invariants(self, rows: list[dict]) -> None:
		for policy in OpeningEntryPolicyMode:
			measures = finalize_measures(aggregate_measures_from_rows(rows, policy, self.window))
			assert_closing_invariant(measures)
			if policy == OpeningEntryPolicyMode.EXCLUDE_OPENING_FLAGGED:
				assert_off_zero_opening_flagged(rows, measures, self.window)
			else:
				assert_on_partition(rows, measures, self.window)

	def test_mixed_rows_satisfy_invariants(self):
		rows = [
			_row(date(2026, 3, 1), debit=400),
			_row(date(2026, 3, 15), debit=100, is_opening="Yes"),
			_row(date(2026, 4, 10), debit=500, credit=50),
			_row(date(2026, 4, 15), debit=300, is_opening="Yes"),
		]
		self._assert_fixture_invariants(rows)


class TestEngineSelection(unittest.TestCase):
	def test_advanced_filters_select_e3(self):
		spec = _spec(accounting=AccountingFilter(account="Cash"))
		self.assertEqual(select_account_axis_engine(spec), AccountAxisEngine.E3_SCOPED_GL)

	@patch(
		"erpnext_extensions.iran_accounting.account_explorer.opening_entry_policy.opening_flagged_baked_in_acb",
		return_value=True,
	)
	@patch(
		"erpnext_extensions.iran_accounting.account_explorer.opening_entry_policy.acb_applicable",
		return_value=True,
	)
	def test_off_acb_opening_baked_selects_e3(self, _acb, _baked):
		spec = _spec(include_opening_entries=False)
		self.assertEqual(select_account_axis_engine(spec), AccountAxisEngine.E3_SCOPED_GL)

	@patch(
		"erpnext_extensions.iran_accounting.account_explorer.opening_entry_policy.opening_flagged_baked_in_acb",
		return_value=False,
	)
	@patch(
		"erpnext_extensions.iran_accounting.account_explorer.opening_entry_policy.acb_applicable",
		return_value=True,
	)
	def test_off_acb_no_opening_baked_selects_e1(self, _acb, _baked):
		spec = _spec(include_opening_entries=False)
		self.assertEqual(select_account_axis_engine(spec), AccountAxisEngine.E1_TB_DELTA)

	@patch(
		"erpnext_extensions.iran_accounting.account_explorer.opening_entry_policy.site_ignore_is_opening",
		return_value=False,
	)
	@patch(
		"erpnext_extensions.iran_accounting.account_explorer.opening_entry_policy.acb_applicable",
		return_value=True,
	)
	def test_on_pcv_ignore_is_opening_false_selects_e2(self, _acb, _ignore):
		spec = _spec(include_opening_entries=True)
		self.assertEqual(select_account_axis_engine(spec), AccountAxisEngine.E2_TB_GAP_SUPPLEMENT)

	@patch(
		"erpnext_extensions.iran_accounting.account_explorer.opening_entry_policy.site_ignore_is_opening",
		return_value=True,
	)
	@patch(
		"erpnext_extensions.iran_accounting.account_explorer.opening_entry_policy.acb_applicable",
		return_value=True,
	)
	def test_on_pcv_ignore_is_opening_true_selects_e1(self, _acb, _ignore):
		spec = _spec(include_opening_entries=True)
		self.assertEqual(select_account_axis_engine(spec), AccountAxisEngine.E1_TB_DELTA)

	def test_plain_spec_selects_e1(self):
		spec = _spec(include_opening_entries=True)
		with patch(
			"erpnext_extensions.iran_accounting.account_explorer.opening_entry_policy.acb_applicable",
			return_value=False,
		):
			self.assertEqual(select_account_axis_engine(spec), AccountAxisEngine.E1_TB_DELTA)


class TestEnginePriority(unittest.TestCase):
	def test_advanced_filters_win_over_acb_fallback(self):
		spec = _spec(
			include_opening_entries=False,
			accounting=AccountingFilter(party="Customer A"),
		)
		with patch(
			"erpnext_extensions.iran_accounting.account_explorer.opening_entry_policy.acb_applicable",
			return_value=True,
		), patch(
			"erpnext_extensions.iran_accounting.account_explorer.opening_entry_policy.opening_flagged_baked_in_acb",
			return_value=True,
		):
			self.assertEqual(select_account_axis_engine(spec), AccountAxisEngine.E3_SCOPED_GL)
