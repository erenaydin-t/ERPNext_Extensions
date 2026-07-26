# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT
"""Framework-free math for hourly leave (مرخصی ساعتی).

Converts a time range within a single working day into leave hours, and leave
hours into the fractional ``total_leave_days`` value stored on Leave
Application. Kept free of Frappe imports so it is unit-testable under plain
``pytest`` (same approach as ``payroll_accrual_grouping``).
"""

from __future__ import annotations

import datetime

#: Scheduled daily working hours: 08:30-17:15 = 8h45m (the legal 44h week
#: compressed into 5 working days). This is the hours a full leave day covers,
#: so it is the divisor converting leave hours to days. Distinct from the
#: 7.33 legal *average* day (44h / 6) used as the payroll overtime rate
#: divisor. Override per employee via ``Employee.custom_daily_working_hours``.
DEFAULT_DAILY_WORKING_HOURS = 8.75

#: Decimals stored on ``custom_leave_hours`` (matches the field precision).
HOURS_PRECISION = 2

#: Decimals stored on ``total_leave_days`` / deducted from the leave ledger.
DAYS_PRECISION = 3


def compute_leave_hours(from_time: datetime.time, to_time: datetime.time) -> float:
	"""Duration between two times of the same day, in hours (2 decimals).

	Raises ``ValueError`` when ``to_time`` is not strictly after ``from_time``.
	"""
	if to_time <= from_time:
		raise ValueError("to_time must be strictly after from_time")

	seconds = (
		(to_time.hour - from_time.hour) * 3600
		+ (to_time.minute - from_time.minute) * 60
		+ (to_time.second - from_time.second)
	)
	return round(seconds / 3600.0, HOURS_PRECISION)


def convert_hours_to_days(hours: float, daily_working_hours: float) -> float:
	"""Fractional day value a given number of leave hours is worth.

	Raises ``ValueError`` on non-positive inputs.
	"""
	if daily_working_hours <= 0:
		raise ValueError("daily_working_hours must be positive")
	if hours <= 0:
		raise ValueError("hours must be positive")
	return round(hours / daily_working_hours, DAYS_PRECISION)
