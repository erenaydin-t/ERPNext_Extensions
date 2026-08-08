# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

import unittest

from frappe.utils import flt, getdate

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

	def test_factor_on_date_and_gaps(self):
		periods = [
			_period("A", "2026-01-01", "2026-03-31", 1.0),
			_period("B", "2026-05-01", "2026-06-30", 0.3, "Percentage", 30),
			_period("C", "2026-08-01", None, 0.0, "No Depreciation"),
		]
		self.assertEqual(factor_on_date(periods, "2026-02-15"), 1.0)
		# Gap April => Normal
		self.assertEqual(factor_on_date(periods, "2026-04-15"), 1.0)
		self.assertEqual(factor_on_date(periods, "2026-05-15"), 0.3)
		# Gap July => Normal
		self.assertEqual(factor_on_date(periods, "2026-07-10"), 1.0)
		self.assertEqual(factor_on_date(periods, "2026-09-01"), 0.0)

	def test_day_weighted_factor(self):
		periods = [
			_period("A", "2026-04-01", "2026-04-10", 1.0),
			_period("B", "2026-04-11", "2026-04-30", 0.3, "Percentage", 30),
		]
		# 10 days @ 1.0 + 20 days @ 0.3 = 16 / 30
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

		# Gap after closed zero => Normal
		closed_zero = [_period("A", "2026-01-01", "2026-03-31", 0.0, "No Depreciation")]
		self.assertTrue(has_future_positive_factor(closed_zero, "2026-02-01"))
