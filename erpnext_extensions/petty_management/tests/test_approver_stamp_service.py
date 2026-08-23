# Copyright (c) 2026, ERPNext Extensions contributors

from __future__ import annotations

import unittest

import frappe

from erpnext_extensions.petty_management.services.approver_stamp_service import (
	resolve_ceo_approver,
	resolve_finance_approver,
	resolve_manager_approver,
	stamp_pm_request_approvers,
)
from erpnext_extensions.petty_management.services.business_status_service import (
	REQ_WAITING_FOR_PAYMENT,
	sync_pm_clearance_business_status,
	sync_pm_request_business_status,
)


class TestApproverStampService(unittest.TestCase):
	def test_resolve_manager_from_employee_expense_approver(self):
		emp = frappe.get_all("Employee", fields=["name", "expense_approver"], limit=20)
		target = None
		for row in emp:
			if row.expense_approver and frappe.db.exists("User", row.expense_approver):
				target = row
				break
		if not target:
			self.skipTest("No Employee with expense_approver on site")
		self.assertEqual(resolve_manager_approver(target.name), target.expense_approver)

	def test_stamp_service_does_not_create_todo(self):
		"""Stamp must not insert ToDo rows."""
		before = frappe.db.count("ToDo")
		doc = frappe._dict(
			employee=frappe.db.get_value("Employee", {}, "name"),
			company=frappe.db.get_value("Company", {}, "name"),
		)
		if not doc.employee:
			self.skipTest("No Employee")
		# May throw if settings missing — that's OK for this assertion path
		try:
			stamp_pm_request_approvers(doc)
		except Exception:
			pass
		self.assertEqual(frappe.db.count("ToDo"), before)

	def test_missing_manager_blocks_when_required(self):
		settings = frappe.get_single("PM Settings")
		settings.db_set("require_named_manager_approver", 1, update_modified=False)
		# Find employee without expense_approver and without dept approvers if possible
		emp = frappe.db.sql(
			"""
			SELECT name FROM `tabEmployee`
			WHERE IFNULL(expense_approver, '') = ''
			LIMIT 1
			"""
		)
		if not emp:
			self.skipTest("No employee without expense_approver")
		doc = frappe._dict(employee=emp[0][0], company=frappe.defaults.get_global_default("company"))
		# Ensure settings have CEO/finance so failure is specifically manager
		if not settings.ceo_approver:
			settings.db_set("ceo_approver", "Administrator", update_modified=False)
		if not settings.finance_manager:
			settings.db_set("finance_manager", "Administrator", update_modified=False)
		with self.assertRaises(frappe.ValidationError):
			stamp_pm_request_approvers(doc)

	def test_ceo_finance_from_settings(self):
		settings = frappe.get_single("PM Settings")
		settings.db_set("ceo_approver", "Administrator", update_modified=False)
		settings.db_set("finance_manager", "Administrator", update_modified=False)
		settings.db_set("finance_supervisor", "Administrator", update_modified=False)
		self.assertEqual(resolve_ceo_approver(), "Administrator")
		self.assertEqual(resolve_finance_approver(context="request"), "Administrator")
		self.assertEqual(resolve_finance_approver(context="clearance"), "Administrator")


class TestPMBusinessStatus(unittest.TestCase):
	def test_request_waiting_and_paid(self):
		doc = frappe._dict(
			docstatus=1,
			workflow_state="Finance Approved",
			payment_status="Not Paid",
			is_closed=0,
			status="Draft",
		)
		# Ensure workflow state row exists
		from erpnext_extensions.petty_management.services.workflow_utils import resolve_workflow_state_link

		doc.workflow_state = resolve_workflow_state_link("Finance Approved")
		sync_pm_request_business_status(doc)
		self.assertEqual(doc.status, REQ_WAITING_FOR_PAYMENT)

		doc.payment_status = "Paid"
		sync_pm_request_business_status(doc)
		self.assertEqual(doc.status, "Paid")

		doc.is_closed = 1
		sync_pm_request_business_status(doc)
		self.assertEqual(doc.status, "Closed")

	def test_clearance_je_does_not_change_workflow_state(self):
		from erpnext_extensions.petty_management.services.workflow_utils import resolve_workflow_state_link

		approved = resolve_workflow_state_link("Approved")
		# Minimal clearance-like object with fake JE submit
		je = frappe.get_all("Journal Entry", filters={"docstatus": 1}, pluck="name", limit=1)
		if not je:
			self.skipTest("No submitted JE")
		doc = frappe._dict(
			docstatus=1,
			workflow_state=approved,
			status="Approved",
			journal_entry=je[0],
			name=None,
		)
		before = doc.workflow_state
		sync_pm_clearance_business_status(doc, persist=False)
		self.assertEqual(doc.workflow_state, before)
		self.assertEqual(doc.status, "Settled")
