# Copyright (c) 2026, ERPNext Extensions contributors
"""v4.5.3: PM Clearance stamp uses role queue (unittest — no ERPNext bootstrap)."""

from __future__ import annotations

import unittest

import frappe

from erpnext_extensions.petty_management.services.approver_stamp_service import (
	stamp_pm_clearance_approvers,
)


class TestApproverStampClearanceV453(unittest.TestCase):
	def test_clearance_stamp_manager_only_not_finance_supervisor(self):
		emp = frappe.db.get_value("Employee", {}, "name")
		company = frappe.db.get_value("Company", {}, "name")
		if not emp or not company:
			self.skipTest("No Employee/Company")
		settings = frappe.get_single("PM Settings")
		prev_supervisor = getattr(settings, "finance_supervisor", None)
		prev_manager = getattr(settings, "finance_manager", None)
		settings.db_set("finance_supervisor", None, update_modified=False)
		settings.db_set("finance_manager", None, update_modified=False)
		frappe.db.set_value("Employee", emp, "expense_approver", "Administrator", update_modified=False)
		try:
			doc = frappe._dict(employee=emp, company=company)
			stamp_pm_clearance_approvers(doc)
			self.assertTrue(doc.manager_approver)
			self.assertFalse((doc.finance_approver or "").strip())
		finally:
			settings.db_set("finance_supervisor", prev_supervisor, update_modified=False)
			settings.db_set("finance_manager", prev_manager, update_modified=False)
