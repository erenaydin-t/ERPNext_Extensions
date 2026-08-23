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
	aggregate_measures_from_rows,
	assert_closing_invariant,
	assert_off_zero_opening_flagged,
	assert_on_partition,
	select_account_axis_engine,
)
from erpnext_extensions.iran_accounting.account_explorer.schemas import (
	AccountExplorerQuerySpec,
	AnalysisContext,
	DocumentScope,
	StatusFilter,
)
from erpnext_extensions.iran_accounting.tests.opening_policy_golden_fixtures import (
	ALL_GOLDEN_FIXTURES,
	FROM_DATE,
	GF_13,
	GF_17,
	GOLDEN_FIXTURES_BY_ID,
	GAP_START,
	PCV_END,
	iter_golden_fixture_ids,
)


def _measure_keys() -> tuple[str, ...]:
	return ("opening_debit", "opening_credit", "period_debit", "period_credit")


class TestGoldenFixtureCatalog(unittest.TestCase):
	def test_all_seventeen_fixtures_registered(self):
		self.assertEqual(len(ALL_GOLDEN_FIXTURES), 17)
		self.assertEqual(iter_golden_fixture_ids(), [f"GF-{idx:02d}" for idx in range(1, 18)])


class TestGoldenFixtureMeasures(unittest.TestCase):
	def test_each_fixture_matches_expected_off_on(self):
		for fixture in ALL_GOLDEN_FIXTURES:
			with self.subTest(fixture_id=fixture.fixture_id):
				window = fixture.window
				off = finalize_measures(
					aggregate_measures_from_rows(
						fixture.rows, OpeningEntryPolicyMode.EXCLUDE_OPENING_FLAGGED, window
					)
				)
				on = finalize_measures(
					aggregate_measures_from_rows(
						fixture.rows, OpeningEntryPolicyMode.INCLUDE_OPENING_FLAGGED, window
					)
				)
				for key in _measure_keys():
					self.assertEqual(off[key], fixture.expected_off[key], f"OFF {key}")
					self.assertEqual(on[key], fixture.expected_on[key], f"ON {key}")

	def test_each_fixture_satisfies_closing_invariant(self):
		for fixture in ALL_GOLDEN_FIXTURES:
			with self.subTest(fixture_id=fixture.fixture_id):
				for policy in OpeningEntryPolicyMode:
					measures = finalize_measures(
						aggregate_measures_from_rows(fixture.rows, policy, fixture.window)
					)
					assert_closing_invariant(measures)

	def test_each_fixture_satisfies_off_and_on_invariants(self):
		for fixture in ALL_GOLDEN_FIXTURES:
			with self.subTest(fixture_id=fixture.fixture_id):
				off = finalize_measures(
					aggregate_measures_from_rows(
						fixture.rows, OpeningEntryPolicyMode.EXCLUDE_OPENING_FLAGGED, fixture.window
					)
				)
				on = finalize_measures(
					aggregate_measures_from_rows(
						fixture.rows, OpeningEntryPolicyMode.INCLUDE_OPENING_FLAGGED, fixture.window
					)
				)
				assert_off_zero_opening_flagged(fixture.rows, off, fixture.window)
				assert_on_partition(fixture.rows, on, fixture.window)


class TestGoldenFixtureEngineExpectations(unittest.TestCase):
	def _spec_from_fixture(self, fixture, *, include_opening_entries: bool) -> AccountExplorerQuerySpec:
		return AccountExplorerQuerySpec(
			document_scope=DocumentScope(
				company="_Test Company",
				from_date=fixture.window.from_date,
				to_date=fixture.window.to_date,
				status=StatusFilter(include_opening_entries=include_opening_entries),
			),
			analysis=AnalysisContext(view_axis="account_level"),
		)

	def test_gf13_off_selects_e3_when_acb_has_opening(self):
		fixture = GF_13
		spec = self._spec_from_fixture(fixture, include_opening_entries=False)
		with patch(
			"erpnext_extensions.iran_accounting.account_explorer.opening_entry_policy.acb_applicable",
			return_value=True,
		), patch(
			"erpnext_extensions.iran_accounting.account_explorer.opening_entry_policy.opening_flagged_baked_in_acb",
			return_value=True,
		):
			self.assertEqual(select_account_axis_engine(spec), AccountAxisEngine.E3_SCOPED_GL)

	def test_gf14_on_selects_e1_or_e2_without_forcing_e3(self):
		fixture = GOLDEN_FIXTURES_BY_ID["GF-14"]
		spec = self._spec_from_fixture(fixture, include_opening_entries=True)
		with patch(
			"erpnext_extensions.iran_accounting.account_explorer.opening_entry_policy.acb_applicable",
			return_value=True,
		), patch(
			"erpnext_extensions.iran_accounting.account_explorer.opening_entry_policy.opening_flagged_baked_in_acb",
			return_value=True,
		), patch(
			"erpnext_extensions.iran_accounting.account_explorer.opening_entry_policy.site_ignore_is_opening",
			return_value=False,
		):
			engine = select_account_axis_engine(spec)
		self.assertIn(engine, (AccountAxisEngine.E1_TB_DELTA, AccountAxisEngine.E2_TB_GAP_SUPPLEMENT))
		self.assertNotEqual(engine, AccountAxisEngine.E3_SCOPED_GL)

	def test_gf17_off_matches_gf13_engine_semantics(self):
		self.assertEqual(GF_17.expected_off, GF_13.expected_off)
		self.assertEqual(GF_17.expected_on, GF_13.expected_on)


class TestAcbPcvScenarios(unittest.TestCase):
	def test_gap_opening_before_from_date_on_only(self):
		fixture = GOLDEN_FIXTURES_BY_ID["GF-15"]
		off = aggregate_measures_from_rows(
			fixture.rows, OpeningEntryPolicyMode.EXCLUDE_OPENING_FLAGGED, fixture.window
		)
		on = aggregate_measures_from_rows(
			fixture.rows, OpeningEntryPolicyMode.INCLUDE_OPENING_FLAGGED, fixture.window
		)
		self.assertEqual(off["opening_debit"], 0)
		self.assertEqual(on["opening_debit"], 150)
		self.assertEqual(GAP_START, date(2026, 1, 1))
		self.assertLess(GAP_START, FROM_DATE)

	def test_in_period_opening_after_pcv_on_turnover_only(self):
		fixture = GOLDEN_FIXTURES_BY_ID["GF-16"]
		on = aggregate_measures_from_rows(
			fixture.rows, OpeningEntryPolicyMode.INCLUDE_OPENING_FLAGGED, fixture.window
		)
		self.assertEqual(on["opening_debit"], 0)
		self.assertEqual(on["period_debit"], 300)

	def test_double_count_sentinel_gf12(self):
		fixture = GOLDEN_FIXTURES_BY_ID["GF-12"]
		on = finalize_measures(
			aggregate_measures_from_rows(
				fixture.rows, OpeningEntryPolicyMode.INCLUDE_OPENING_FLAGGED, fixture.window
			)
		)
		off = finalize_measures(
			aggregate_measures_from_rows(
				fixture.rows, OpeningEntryPolicyMode.EXCLUDE_OPENING_FLAGGED, fixture.window
			)
		)
		self.assertEqual(off["period_debit"], 50)
		self.assertEqual(on["opening_debit"], 100)
		self.assertEqual(on["period_debit"], 350)
		assert_on_partition(fixture.rows, on, fixture.window)

	def test_normal_plus_opening_before_pcv(self):
		fixture = GOLDEN_FIXTURES_BY_ID["GF-17"]
		off = aggregate_measures_from_rows(
			fixture.rows, OpeningEntryPolicyMode.EXCLUDE_OPENING_FLAGGED, fixture.window
		)
		on = aggregate_measures_from_rows(
			fixture.rows, OpeningEntryPolicyMode.INCLUDE_OPENING_FLAGGED, fixture.window
		)
		self.assertEqual(off["opening_debit"], 800)
		self.assertEqual(on["opening_debit"], 1000)
		self.assertLess(date(2025, 10, 2), PCV_END)
