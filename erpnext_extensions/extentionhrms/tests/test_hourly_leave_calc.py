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
	def test_iranian_legal_daily_hours(self):
		# The acceptance case: 2 hours on the 7.33h legal day.
		assert convert_hours_to_days(2, DEFAULT_DAILY_WORKING_HOURS) == 0.273

	def test_acceptance_balance_deduction(self):
		# 26 days balance minus a 2-hour leave leaves 25.727 days.
		balance = round(26 - convert_hours_to_days(2, 7.33), 3)
		assert balance == 25.727

	def test_custom_daily_hours(self):
		assert convert_hours_to_days(4, 8) == 0.5

	def test_sub_day_balance_still_representable(self):
		# An employee with 0.4 days left can take a 2h leave (0.273 < 0.4).
		assert convert_hours_to_days(2, 7.33) < 0.4

	def test_rounding_is_three_decimals(self):
		assert convert_hours_to_days(1, 7.33) == round(1 / 7.33, 3)

	def test_zero_hours_rejected(self):
		with pytest.raises(ValueError):
			convert_hours_to_days(0, 7.33)

	def test_zero_daily_hours_rejected(self):
		with pytest.raises(ValueError):
			convert_hours_to_days(2, 0)
