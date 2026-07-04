# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT
"""Custom fields required by the payroll accrual override.

Adds ``Company.custom_payroll_round_off_department`` — the Department stamped on
the accrual round-off line (the round-off account is P&L, so the line needs a
Department). Created idempotently on ``after_migrate``.
"""

from __future__ import annotations

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

ROUND_OFF_DEPARTMENT_FIELD = {
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
	]
}


def create_payroll_round_off_department_field() -> None:
	create_custom_fields(ROUND_OFF_DEPARTMENT_FIELD, ignore_validate=True)


def after_migrate() -> None:
	create_payroll_round_off_department_field()
	frappe.db.commit()
