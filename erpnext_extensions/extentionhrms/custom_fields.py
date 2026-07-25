# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT
"""Custom fields used by the payroll accrual override.

* ``Company.custom_payroll_round_off_department`` — the Department stamped on the
  accrual round-off line (the round-off account is P&L, so the line needs one).
* ``Salary Component.custom_process_based_on_employee`` — when checked, the
  component bypasses the Cost Center / Department group-by and is booked as a
  separate row per employee (with the Employee as Party). Intended for
  employee-tied components such as loans (``وام``) and advances (``مساعده``) so
  accountants can reconcile per-person repayments.

Created idempotently on ``after_migrate``.
"""

from __future__ import annotations

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

# Fieldname read by the override to decide which components skip aggregation.
PROCESS_BASED_ON_EMPLOYEE_FIELD = "custom_process_based_on_employee"

CUSTOM_FIELDS = {
	"Company": [
		{
			"fieldname": "custom_payroll_round_off_department",
			"label": "Payroll Round-Off Department",
			"fieldtype": "Link",
			"options": "Department",
			"insert_after": "round_off_cost_center",
			"description": (
				"Department booked on the payroll accrual round-off line. "
				"Required when a mandatory-for-P&L Accounting Dimension (e.g. "
				"Department) is enabled, because the round-off account is P&L."
			),
		}
	],
	"Salary Component": [
		{
			"fieldname": PROCESS_BASED_ON_EMPLOYEE_FIELD,
			"label": "Process Based on Employee",
			"fieldtype": "Check",
			"insert_after": "accounts",
			"description": (
				"If checked, payroll accounting entries for this component bypass "
				"the Cost Center / Department aggregation: a separate Journal Entry "
				"row is generated for each employee, with the Employee set as Party. "
				"Use for employee-tied components such as loans and advances."
			),
		}
	],
	# Party defaults on the per-company account mapping. Lets the accrual stamp a
	# fixed Party (e.g. the SSO / tax Supplier) on the generated rows for this
	# account — replacing the old party-assignment Server Script.
	"Salary Component Account": [
		{
			"fieldname": "custom_party_type",
			"label": "Party Type",
			"fieldtype": "Link",
			"options": "Party Type",
			"insert_after": "account",
		},
		{
			"fieldname": "custom_party",
			"label": "Party",
			"fieldtype": "Dynamic Link",
			"options": "custom_party_type",
			"insert_after": "custom_party_type",
		},
	],
}


# Fields backing the hourly leave override — see ``leave_application_override``.
# ``custom_daily_working_hours`` defaults to the scheduled daily hours
# (08:30-17:15 = 8.75h, the 44h legal week over 5 days) and is the divisor
# converting leave hours to days.
HOURLY_LEAVE_CUSTOM_FIELDS = {
	"Leave Application": [
		{
			"fieldname": "custom_is_hourly",
			"label": "Is Hourly Leave",
			"fieldtype": "Check",
			"insert_after": "to_date",
			"description": (
				"Single-day leave measured in hours, deducted from the same "
				"balance as a fraction of a day."
			),
		},
		{
			"fieldname": "custom_from_time",
			"label": "From Time",
			"fieldtype": "Time",
			"insert_after": "custom_is_hourly",
			"depends_on": "eval:doc.custom_is_hourly",
			"mandatory_depends_on": "eval:doc.custom_is_hourly",
		},
		{
			"fieldname": "custom_to_time",
			"label": "To Time",
			"fieldtype": "Time",
			"insert_after": "custom_from_time",
			"depends_on": "eval:doc.custom_is_hourly",
			"mandatory_depends_on": "eval:doc.custom_is_hourly",
		},
		{
			"fieldname": "custom_leave_hours",
			"label": "Leave Hours",
			"fieldtype": "Float",
			"insert_after": "custom_to_time",
			"read_only": 1,
			"no_copy": 1,
			"precision": "2",
			"depends_on": "eval:doc.custom_is_hourly",
		},
	],
	"Employee": [
		{
			"fieldname": "custom_daily_working_hours",
			"label": "Daily Working Hours",
			"fieldtype": "Float",
			"insert_after": "holiday_list",
			"default": "8.75",
			"precision": "2",
			"description": (
				"Scheduled daily working hours used to convert hourly leave "
				"into fractional days (08:30-17:15 = 8.75h; the 44h legal "
				"week over 5 working days)."
			),
		},
	],
}


def create_payroll_custom_fields() -> None:
	create_custom_fields(CUSTOM_FIELDS, ignore_validate=True)


def create_hourly_leave_custom_fields() -> None:
	create_custom_fields(HOURLY_LEAVE_CUSTOM_FIELDS, ignore_validate=True)


# Backwards-compatible alias (used by install.after_migrate).
def create_payroll_round_off_department_field() -> None:
	create_payroll_custom_fields()


def after_migrate() -> None:
	create_payroll_custom_fields()
	frappe.db.commit()
