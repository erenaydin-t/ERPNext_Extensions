# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT
"""Unit tests for the framework-free hourly leave math.

These tests import **no Frappe** and run under plain ``pytest``::

    pytest erpnext_extensions/extentionhrms/tests/test_hourly_leave_calc.py
"""

from __future__ import annotations

import datetime

import pytest

from erpnext_extensions.extentionhrms.hourly_leave_calc import (
	DEFAULT_DAILY_WORKING_HOURS,
	compute_leave_hours,
	convert_hours_to_days,
)


def t(hour, minute=0, second=0):
	return datetime.time(hour, minute, second)


class TestComputeLeaveHours:
	def test_whole_hours(self):
		assert compute_leave_hours(t(9), t(11)) == 2.0

	def test_minutes_are_fractional(self):
		assert compute_leave_hours(t(9), t(10, 30)) == 1.5
		assert compute_leave_hours(t(8, 45), t(9, 0)) == 0.25

	def test_seconds_round_to_two_decimals(self):
		assert compute_leave_hours(t(9, 0, 0), t(9, 10, 0)) == round(10 / 60, 2)

	def test_equal_times_rejected(self):
		with pytest.raises(ValueError):
			compute_leave_hours(t(9), t(9))

	def test_inverted_times_rejected(self):
		with pytest.raises(ValueError):
			compute_leave_hours(t(11), t(9))


class TestConvertHoursToDays:
	def test_scheduled_daily_hours_default(self):
		# The 08:30-17:15 workday is 8h45m = 8.75 decimal hours.
		assert DEFAULT_DAILY_WORKING_HOURS == 8.75
		# The acceptance case: a 2-hour leave on that day.
		assert convert_hours_to_days(2, DEFAULT_DAILY_WORKING_HOURS) == 0.229

	def test_acceptance_balance_deduction(self):
		# 26 days balance minus a 2-hour leave leaves 25.771 days.
		balance = round(26 - convert_hours_to_days(2, 8.75), 3)
		assert balance == 25.771

	def test_full_day_in_hourly_chunks_costs_one_day(self):
		# 8.75 hours of hourly leave must equal exactly one day.
		assert convert_hours_to_days(8.75, 8.75) == 1.0

	def test_custom_daily_hours(self):
		assert convert_hours_to_days(4, 8) == 0.5
		# The 7.33 legal-average day stays usable as a per-employee override.
		assert convert_hours_to_days(2, 7.33) == 0.273

	def test_sub_day_balance_still_representable(self):
		# An employee with 0.4 days left can take a 2h leave (0.229 < 0.4).
		assert convert_hours_to_days(2, 8.75) < 0.4

	def test_rounding_is_three_decimals(self):
		assert convert_hours_to_days(1, 8.75) == round(1 / 8.75, 3)

	def test_zero_hours_rejected(self):
		with pytest.raises(ValueError):
			convert_hours_to_days(0, 8.75)

	def test_zero_daily_hours_rejected(self):
		with pytest.raises(ValueError):
			convert_hours_to_days(2, 0)
