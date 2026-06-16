# Copyright (c) 2026, Farbod Siyahpoosh and contributors
"""Ledger-only tests for opening advance allocation (no PI/PE settlement)."""

from __future__ import annotations

import unittest

import frappe
from frappe.utils import today

from erpnext_extensions.petty_management.services.opening_advance_service import (
	get_opening_advance_available_amount,
	sum_prior_opening_allocations,
)
import erpnext_extensions.petty_management.tests.test_pm_clearance as pm_ct


def _insert_opening_allocation_seed(
	parent_clearance: str, opening_advance: str, amount: float, *, docstatus: int = 1
) -> None:
	name = frappe.generate_hash(length=10)
	frappe.db.sql(
		"""
		INSERT INTO `tabPM Clearance Request Allocation`
		(`name`, `creation`, `modified`, `modified_by`, `owner`, `docstatus`,
		 `parent`, `parenttype`, `parentfield`, `idx`,
		 `funding_source_type`, `pm_opening_advance`, `allocated_amount`, `pm_request`)
		VALUES
		(%s, NOW(), NOW(), 'Administrator', 'Administrator', 0,
		 %s, 'PM Clearance', 'request_allocations', 1,
		 'PM Opening Advance', %s, %s, NULL)
		""",
		(name, parent_clearance, opening_advance, amount),
	)
	frappe.db.set_value("PM Clearance", parent_clearance, {"docstatus": docstatus, "status": "Approved"})


def _make_clearance_shell(emp: str) -> str:
	cl = frappe.new_doc("PM Clearance")
	cl.company = pm_ct.COMPANY
	cl.employee = emp
	cl.transaction_date = today()
	cl.flags.ignore_validate = True
	cl.flags.ignore_mandatory = True
	cl.insert(ignore_permissions=True)
	return cl.name


class TestOpeningAdvanceLedger(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")
		pm_ct._ensure_company_context()
		if not pm_ct.COMPANY:
			raise unittest.SkipTest("No Company on site")
		pm_ct._ensure_petty_account()

	def test_cancelled_clearance_does_not_reserve_opening(self):
		emp = pm_ct._make_employee()
		holder = pm_ct._make_holder(emp)
		oa = frappe.new_doc("PM Opening Advance")
		oa.holder = holder
		oa.opening_date = today()
		oa.opening_source_type = "Opening Balance"
		oa.opening_advance_amount = 100_000
		oa.previously_settled_before_migration = 0
		oa.insert(ignore_permissions=True)
		oa.submit()

		cl = frappe.new_doc("PM Clearance")
		cl.company = pm_ct.COMPANY
		cl.employee = emp
		cl.transaction_date = today()
		cl.flags.ignore_validate = True
		cl.flags.ignore_mandatory = True
		cl.insert(ignore_permissions=True)
		_insert_opening_allocation_seed(cl.name, oa.name, 20_000, docstatus=1)
		self.assertEqual(get_opening_advance_available_amount(oa.name), 80_000)

		frappe.db.set_value(
			"PM Clearance",
			cl.name,
			{"docstatus": 2, "status": "Cancelled"},
			update_modified=False,
		)
		self.assertEqual(sum_prior_opening_allocations(oa.name), 0)
		self.assertEqual(get_opening_advance_available_amount(oa.name), 100_000)

	def test_middle_clearance_cancel_restores_opening_availability(self):
		emp = pm_ct._make_employee()
		holder = pm_ct._make_holder(emp)
		oa = frappe.new_doc("PM Opening Advance")
		oa.holder = holder
		oa.opening_date = today()
		oa.opening_source_type = "Opening Balance"
		oa.opening_advance_amount = 100_000
		oa.previously_settled_before_migration = 0
		oa.insert(ignore_permissions=True)
		oa.submit()

		cl_a = _make_clearance_shell(emp)
		cl_b = _make_clearance_shell(emp)
		cl_c = _make_clearance_shell(emp)
		_insert_opening_allocation_seed(cl_a, oa.name, 30_000, docstatus=1)
		_insert_opening_allocation_seed(cl_b, oa.name, 20_000, docstatus=1)
		_insert_opening_allocation_seed(cl_c, oa.name, 10_000, docstatus=1)
		self.assertEqual(get_opening_advance_available_amount(oa.name), 40_000)

		frappe.db.set_value(
			"PM Clearance",
			cl_b,
			{"docstatus": 2, "status": "Cancelled"},
			update_modified=False,
		)
		self.assertEqual(sum_prior_opening_allocations(oa.name), 40_000)
		self.assertEqual(get_opening_advance_available_amount(oa.name), 60_000)
