# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT
"""Hourly leave support for the HRMS ``Leave Application``.

Frappe HR only knows full-day and half-day leave. Iranian labor law also
grants *hourly* leave (مرخصی ساعتی) taken out of the same yearly entitlement.
This override models hourly leave as a **fraction of a day** on the standard
Leave Application, so the deduction hits the same Leave Ledger / allocation
and no separate Leave Type is needed:

* ``custom_is_hourly`` (Check) switches the application into hourly mode.
* ``custom_from_time`` / ``custom_to_time`` (Time) bound the absence within a
  single day; ``custom_leave_hours`` (Float, read-only) stores the duration.
* ``total_leave_days`` becomes ``hours / daily working hours`` (3 decimals).
  The divisor comes from ``Employee.custom_daily_working_hours`` (default
  7.33 — the Iranian legal daily hours). Leave Ledger Entry accepts
  fractional leaves, so submit/cancel bookkeeping works unchanged.

Behavior changes in hourly mode (each method falls through to the parent when
``custom_is_hourly`` is unchecked):

* ``validate_balance_leaves`` — the parent recomputes ``total_leave_days``
  via ``get_number_of_leave_days`` (1.0 for a single day) and rejects the
  application when the balance is below that. The override runs the same
  check against the *fractional* value, so an employee with e.g. 0.4 days
  left can still take a 2-hour leave.
* ``validate_attendance`` — skipped: the employee is present most of the
  day, so an existing submitted Present attendance must not block the leave.
* ``update_attendance`` / ``cancel_attendance`` — skipped: the checkin-based
  attendance (working hours → overtime pipeline) owns the day; hourly leave
  must not convert it to "On Leave".

Known limitations (v1): the parent's overlap validation still allows only one
leave application per calendar day, so a second hourly leave on the same day
is rejected. Hourly leave on Leave-Without-Pay types is blocked — payroll
Loss of Pay only understands half and full days.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, flt, get_time
from hrms.hr.doctype.leave_application.leave_application import (
	LeaveApplication,
	get_leave_balance_on,
	get_number_of_leave_days,
	is_lwp,
)

from erpnext_extensions.extentionhrms.hourly_leave_calc import (
	DEFAULT_DAILY_WORKING_HOURS,
	compute_leave_hours,
	convert_hours_to_days,
)

DAILY_WORKING_HOURS_FIELD = "custom_daily_working_hours"


class LeaveApplicationWithHourlyLeave(LeaveApplication):
	"""Leave Application that can be filed for a few hours of a single day."""

	def is_hourly(self) -> bool:
		return cint(self.get("custom_is_hourly")) == 1

	# ------------------------------------------------------------------ #
	# validation                                                          #
	# ------------------------------------------------------------------ #

	def validate(self):
		if self.is_hourly():
			self.normalize_hourly_leave()
		super().validate()

	def normalize_hourly_leave(self) -> None:
		"""Coerce the document into a consistent single-day hourly shape."""
		if not self.from_date:
			frappe.throw(_("From Date is mandatory for hourly leave"))

		if is_lwp(self.leave_type):
			frappe.throw(
				_(
					"Hourly leave is not supported for Leave Without Pay type {0}: "
					"payroll Loss of Pay only understands half and full days"
				).format(frappe.bold(self.leave_type))
			)

		# Hourly leave is single-day only and never a half day.
		self.to_date = self.from_date
		self.half_day = 0
		self.half_day_date = None

		if not self.custom_from_time or not self.custom_to_time:
			frappe.throw(_("From Time and To Time are mandatory for hourly leave"))

		try:
			self.custom_leave_hours = compute_leave_hours(
				get_time(self.custom_from_time), get_time(self.custom_to_time)
			)
		except ValueError:
			frappe.throw(_("To Time must be after From Time"))

		daily_hours = self.get_daily_working_hours()
		if flt(self.custom_leave_hours) >= daily_hours:
			frappe.throw(
				_(
					"Hourly leave of {0} hours reaches the daily working hours "
					"({1}). Apply for a normal full-day leave instead."
				).format(self.custom_leave_hours, daily_hours)
			)

	def get_daily_working_hours(self) -> float:
		hours = 0.0
		if self.employee:
			hours = flt(
				frappe.db.get_value("Employee", self.employee, DAILY_WORKING_HOURS_FIELD)
			)
		return hours or DEFAULT_DAILY_WORKING_HOURS

	# ------------------------------------------------------------------ #
	# balance                                                             #
	# ------------------------------------------------------------------ #

	def validate_balance_leaves(self):
		"""Parent balance check, but against the fractional day value."""
		if not self.is_hourly():
			return super().validate_balance_leaves()

		# Same guard as the parent: a zero day count means the chosen date is
		# a holiday / non-working day.
		day_count = get_number_of_leave_days(
			self.employee, self.leave_type, self.from_date, self.to_date, 0, None
		)
		if day_count <= 0:
			frappe.throw(
				_(
					"The day(s) on which you are applying for leave are holidays. "
					"You need not apply for leave."
				)
			)

		self.total_leave_days = convert_hours_to_days(
			flt(self.custom_leave_hours), self.get_daily_working_hours()
		)

		precision = (
			cint(frappe.db.get_single_value("System Settings", "float_precision")) or 2
		)
		leave_balance = get_leave_balance_on(
			self.employee,
			self.leave_type,
			self.from_date,
			self.to_date,
			consider_all_leaves_in_the_allocation_period=True,
			for_consumption=True,
		)
		leave_balance_for_consumption = flt(
			leave_balance.get("leave_balance_for_consumption"), precision
		)
		if self.status != "Rejected" and (
			leave_balance_for_consumption < self.total_leave_days
			or not leave_balance_for_consumption
		):
			self.show_insufficient_balance_message(leave_balance_for_consumption)

	# ------------------------------------------------------------------ #
	# attendance                                                          #
	# ------------------------------------------------------------------ #

	def validate_attendance(self):
		if self.is_hourly():
			return
		super().validate_attendance()

	def update_attendance(self):
		if self.is_hourly():
			return
		super().update_attendance()

	def cancel_attendance(self):
		if self.is_hourly():
			return
		super().cancel_attendance()
