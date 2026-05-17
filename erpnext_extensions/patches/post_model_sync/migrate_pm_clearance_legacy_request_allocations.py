# Copyright (c) 2026, Farbod Siyahpoosh and contributors
# For license information, please see license.txt

"""Backfill one legacy PM Request allocation row per PM Clearance missing allocation lines.

Legacy rows: is_legacy_row=1, empty pm_request, allocated_amount = total_expense_amount.
They are excluded from PM Request availability calculations (see sum_prior_pm_request_allocations).
"""

from __future__ import annotations

import frappe
from frappe.utils import flt


def _insert_legacy_child_row(parent: str, total: float) -> None:
	"""Insert child row without loading/saving submitted PM Clearance parents."""
	name = frappe.generate_hash(length=10)
	user = "Administrator"
	frappe.db.sql(
		"""
		INSERT INTO `tabPM Clearance Request Allocation`
		(`name`, `creation`, `modified`, `modified_by`, `owner`, `docstatus`,
		 `parent`, `parenttype`, `parentfield`, `idx`,
		 `is_legacy_row`, `allocated_amount`, `request_amount`, `paid_amount`,
		 `previously_allocated_amount`, `available_amount`, `pm_request`)
		VALUES
		(%s, NOW(), NOW(), %s, %s, 0,
		 %s, 'PM Clearance', 'request_allocations', 1,
		 1, %s, 0, 0, 0, 0, NULL)
		""",
		(name, user, user, parent, total),
	)


def execute():
	if not frappe.db.has_table("tabPM Clearance Request Allocation"):
		return

	clearances = frappe.db.sql(
		"""
		select pc.name, pc.total_expense_amount, pc.docstatus
		from `tabPM Clearance` pc
		where pc.docstatus != 2
			and not exists (
				select 1
				from `tabPM Clearance Request Allocation` c
				where c.parent = pc.name
					and c.parenttype = 'PM Clearance'
					and c.parentfield = 'request_allocations'
			)
		""",
		as_dict=True,
	)

	for row in clearances:
		total = flt(row.total_expense_amount)
		if row.docstatus == 0:
			doc = frappe.get_doc("PM Clearance", row.name)
			doc.append(
				"request_allocations",
				{
					"is_legacy_row": 1,
					"allocated_amount": total,
					"request_amount": 0,
					"paid_amount": 0,
					"previously_allocated_amount": 0,
					"available_amount": 0,
				},
			)
			doc.flags.ignore_validate = True
			doc.save(ignore_permissions=True)
		else:
			_insert_legacy_child_row(row.name, total)
