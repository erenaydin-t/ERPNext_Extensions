# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

"""Usage timeline unit tests — including LOCKED default Normal = 1.0 rule."""

from __future__ import annotations

import unittest

from frappe.utils import flt, getdate

from erpnext_extensions.asset_usage_depreciation.constants import DEFAULT_USAGE_FACTOR
from erpnext_extensions.asset_usage_depreciation.services.usage_timeline import (
	day_weighted_factor,
	factor_on_date,
	has_future_positive_factor,
	mode_to_factor,
	validate_timeline_consistency,
)


def _period(name, from_date, to_date, factor, mode="Normal", percentage=None):
	return {
		"name": name,
		"from_date": getdate(from_date),
		"to_date": getdate(to_date) if to_date else None,
		"factor": factor,
		"depreciation_mode": mode,
		"depreciation_percentage": percentage,
	}


class TestUsageTimeline(unittest.TestCase):
	def test_mode_to_factor(self):
		self.assertEqual(mode_to_factor("Normal"), 1.0)
		self.assertEqual(mode_to_factor("No Depreciation"), 0.0)
		self.assertEqual(mode_to_factor("Percentage", 30), 0.3)

	def test_default_factor_constant_is_normal(self):
		self.assertEqual(DEFAULT_USAGE_FACTOR, 1.0)

	def test_no_usage_periods_defaults_to_normal(self):
		"""Req 1: empty timeline → factor 1.0 on any date."""
		self.assertEqual(factor_on_date([], "2026-01-01"), DEFAULT_USAGE_FACTOR)
		self.assertEqual(factor_on_date([], "2026-06-15"), DEFAULT_USAGE_FACTOR)
		self.assertEqual(factor_on_date([], "2027-12-31"), DEFAULT_USAGE_FACTOR)

	def test_date_before_first_period_defaults_to_normal(self):
		"""Req 2 / Example 2: before first Usage Period → Normal."""
		periods = [_period("A", "2026-04-01", None, 0.3, "Percentage", 30)]
		self.assertEqual(factor_on_date(periods, "2026-01-01"), DEFAULT_USAGE_FACTOR)
		self.assertEqual(factor_on_date(periods, "2026-03-31"), DEFAULT_USAGE_FACTOR)
		self.assertEqual(factor_on_date(periods, "2026-04-01"), 0.3)

	def test_date_inside_percentage_period(self):
		"""Req 3."""
		periods = [_period("A", "2026-04-01", "2026-06-30", 0.3, "Percentage", 30)]
		self.assertEqual(factor_on_date(periods, "2026-05-15"), 0.3)

	def test_after_closed_percentage_with_no_next_defaults_to_normal(self):
		"""Req 4."""
		periods = [_period("A", "2026-04-01", "2026-06-30", 0.3, "Percentage", 30)]
		self.assertEqual(factor_on_date(periods, "2026-07-01"), DEFAULT_USAGE_FACTOR)
		self.assertEqual(factor_on_date(periods, "2026-12-31"), DEFAULT_USAGE_FACTOR)

	def test_gap_between_periods_defaults_to_normal(self):
		"""Req 5 / Example 4 gap Jul–Sep."""
		periods = [
			_period("A", "2026-04-01", "2026-06-30", 0.3, "Percentage", 30),
			_period("B", "2026-10-01", None, 0.0, "No Depreciation"),
		]
		self.assertEqual(factor_on_date(periods, "2026-03-01"), DEFAULT_USAGE_FACTOR)
		self.assertEqual(factor_on_date(periods, "2026-05-01"), 0.3)
		self.assertEqual(factor_on_date(periods, "2026-07-01"), DEFAULT_USAGE_FACTOR)
		self.assertEqual(factor_on_date(periods, "2026-09-30"), DEFAULT_USAGE_FACTOR)
		self.assertEqual(factor_on_date(periods, "2026-10-01"), 0.0)

	def test_explicit_normal_period(self):
		"""Req 6: explicit Normal still resolves to 1.0."""
		periods = [_period("A", "2026-07-01", None, 1.0, "Normal")]
		self.assertEqual(factor_on_date(periods, "2026-08-01"), 1.0)
		self.assertEqual(factor_on_date(periods, "2026-08-01"), DEFAULT_USAGE_FACTOR)

	def test_percentage_normal_percentage_repeated_transitions(self):
		"""Req 7: alternating status-change timeline."""
		periods = [
			_period("A", "2026-02-01", "2026-04-30", 0.3, "Percentage", 30),
			_period("B", "2026-05-01", "2026-08-31", 1.0, "Normal"),
			_period("C", "2026-09-01", "2026-12-31", 0.3, "Percentage", 30),
			_period("D", "2027-01-01", None, 1.0, "Normal"),
		]
		validate_timeline_consistency(periods)
		self.assertEqual(factor_on_date(periods, "2026-01-15"), DEFAULT_USAGE_FACTOR)  # before first
		self.assertEqual(factor_on_date(periods, "2026-03-01"), 0.3)
		self.assertEqual(factor_on_date(periods, "2026-06-01"), 1.0)
		self.assertEqual(factor_on_date(periods, "2026-10-01"), 0.3)
		self.assertEqual(factor_on_date(periods, "2027-02-01"), 1.0)

	def test_no_depreciation_gap_then_percentage(self):
		"""Req 8: gap after No Depreciation → Normal 1.0."""
		periods = [
			_period("A", "2026-01-01", "2026-03-31", 0.0, "No Depreciation"),
			_period("B", "2026-07-01", None, 0.3, "Percentage", 30),
		]
		self.assertEqual(factor_on_date(periods, "2026-02-01"), 0.0)
		self.assertEqual(factor_on_date(periods, "2026-05-01"), DEFAULT_USAGE_FACTOR)
		self.assertEqual(factor_on_date(periods, "2026-07-15"), 0.3)

	def test_daily_prorata_across_implicit_normal_and_percentage(self):
		"""Req 9: window window spanning implicit Normal + explicit 30%."""
		# Apr 1–10 uncovered (Normal), Apr 11–30 at 30%
		periods = [_period("A", "2026-04-11", "2026-04-30", 0.3, "Percentage", 30)]
		expected = (10 * 1.0 + 20 * 0.3) / 30.0
		self.assertAlmostEqual(
			day_weighted_factor(periods, "2026-04-01", "2026-04-30"),
			expected,
		)

	def test_factor_on_date_and_gaps(self):
		periods = [
			_period("A", "2026-01-01", "2026-03-31", 1.0),
			_period("B", "2026-05-01", "2026-06-30", 0.3, "Percentage", 30),
			_period("C", "2026-08-01", None, 0.0, "No Depreciation"),
		]
		self.assertEqual(factor_on_date(periods, "2026-02-15"), 1.0)
		self.assertEqual(factor_on_date(periods, "2026-04-15"), DEFAULT_USAGE_FACTOR)
		self.assertEqual(factor_on_date(periods, "2026-05-15"), 0.3)
		self.assertEqual(factor_on_date(periods, "2026-07-10"), DEFAULT_USAGE_FACTOR)
		self.assertEqual(factor_on_date(periods, "2026-09-01"), 0.0)

	def test_day_weighted_factor(self):
		periods = [
			_period("A", "2026-04-01", "2026-04-10", 1.0),
			_period("B", "2026-04-11", "2026-04-30", 0.3, "Percentage", 30),
		]
		self.assertAlmostEqual(day_weighted_factor(periods, "2026-04-01", "2026-04-30"), 16.0 / 30.0)

	def test_overlap_rejected(self):
		periods = [
			_period("A", "2026-01-01", "2026-03-31", 1.0),
			_period("B", "2026-03-01", "2026-04-30", 0.3),
		]
		with self.assertRaises(Exception):
			validate_timeline_consistency(periods)

	def test_open_ended_must_be_latest(self):
		periods = [
			_period("A", "2026-01-01", None, 1.0),
			_period("B", "2026-06-01", "2026-07-01", 0.3),
		]
		with self.assertRaises(Exception):
			validate_timeline_consistency(periods)

	def test_has_future_positive_factor(self):
		open_zero = [_period("A", "2026-01-01", None, 0.0, "No Depreciation")]
		self.assertFalse(has_future_positive_factor(open_zero, "2026-02-01"))

		with_later = [
			_period("A", "2026-01-01", "2026-03-31", 0.0, "No Depreciation"),
			_period("B", "2026-06-01", None, 1.0),
		]
		self.assertTrue(has_future_positive_factor(with_later, "2026-02-01"))

		closed_zero = [_period("A", "2026-01-01", "2026-03-31", 0.0, "No Depreciation")]
		self.assertTrue(has_future_positive_factor(closed_zero, "2026-02-01"))
