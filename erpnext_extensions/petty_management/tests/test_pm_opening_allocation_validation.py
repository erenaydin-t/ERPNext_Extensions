# Copyright (c) 2026, Farbod Siyahpoosh and contributors
"""Funding allocation validation without Purchase Invoice submit."""

from __future__ import annotations

import unittest

import frappe
from frappe.exceptions import ValidationError
from frappe.utils import flt

from erpnext_extensions.petty_management.services.opening_advance_service import (
	get_opening_advance_allocation_context,
	get_opening_advance_available_amount,
)
import erpnext_extensions.petty_management.tests.test_pm_allocation_helpers as ah
import erpnext_extensions.petty_management.tests.test_pm_clearance as pm_ct


class TestPMOpeningAllocationValidation(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")
		ah.ensure_site_context()
		pm_ct._ensure_petty_account()

	def test_opening_allocation_snapshot_fields(self):
		emp = pm_ct._make_employee()
		holder = pm_ct._make_holder(emp)
		petty = frappe.db.get_value("PM Holder", holder, "petty_cash_account")
		oa = ah.make_submitted_opening(holder, 12_000, 4_000)
		ctx = get_opening_advance_allocation_context(
			oa,
			company=pm_ct.COMPANY,
			employee=emp,
			holder=holder,
			petty_cash_account=petty,
		)
		self.assertEqual(flt(ctx["request_amount"]), 12_000)
		self.assertEqual(flt(ctx["paid_amount"]), 8_000)
		self.assertEqual(flt(ctx["available_amount"]), 8_000)
		self.assertEqual(get_opening_advance_available_amount(oa), 8_000)

	def test_over_allocation_fails_without_pi(self):
		emp = pm_ct._make_employee()
		holder = pm_ct._make_holder(emp)
		oa = ah.make_submitted_opening(holder, 10_000, 0)
		cl = ah.build_clearance_for_allocation_validation(emp, holder, 11_000)
		ah.append_opening_allocation_row(cl, oa, 11_000)
		ah.normalize_funding_rows(cl)
		with self.assertRaises(ValidationError):
			ah.run_allocation_validation(cl)

	def test_normalize_clears_pm_request_on_opening_row(self):
		emp = pm_ct._make_employee()
		holder = pm_ct._make_holder(emp)
		oa = ah.make_submitted_opening(holder, 10_000, 0)
		cl = ah.build_clearance_for_allocation_validation(emp, holder, 2_000)
		ah.append_opening_allocation_row(cl, oa, 2_000, pm_request="SHOULD-CLEAR")
		ah.normalize_funding_rows(cl)
		row = cl.request_allocations[0]
		self.assertFalse(row.pm_request)
		ah.run_allocation_validation(cl)
		self.assertFalse(cl.request_allocations[0].pm_request)

	def test_normalize_clears_opening_on_pm_request_row(self):
		emp = pm_ct._make_employee()
		holder = pm_ct._make_holder(emp)
		req_name, _pe = pm_ct._fund_pm_request(emp, 10_000.0)
		cl = ah.build_clearance_for_allocation_validation(emp, holder, 3_000)
		ah.append_pm_request_allocation_row(cl, req_name, 3_000, pm_opening_advance="SHOULD-CLEAR")
		ah.normalize_funding_rows(cl)
		row = cl.request_allocations[0]
		self.assertFalse(row.pm_opening_advance)
		ah.run_allocation_validation(cl)
		self.assertGreater(flt(cl.request_allocations[0].paid_amount), 0)

	def test_opening_row_does_not_require_pm_request(self):
		emp = pm_ct._make_employee()
		holder = pm_ct._make_holder(emp)
		oa = ah.make_submitted_opening(holder, 10_000, 0)
		cl = ah.build_clearance_for_allocation_validation(emp, holder, 2_000)
		ah.append_opening_allocation_row(cl, oa, 2_000)
		ah.normalize_funding_rows(cl)
		ah.run_allocation_validation(cl)
		row = cl.request_allocations[0]
		self.assertEqual(row.funding_source_type, "PM Opening Advance")
		self.assertEqual(flt(row.available_amount), 10_000)
		self.assertEqual(flt(row.allocated_amount), 2_000)

	def test_pm_request_row_does_not_require_opening_advance(self):
		emp = pm_ct._make_employee()
		holder = pm_ct._make_holder(emp)
		req_name, _pe = pm_ct._fund_pm_request(emp, 8_000.0)
		cl = ah.build_clearance_for_allocation_validation(emp, holder, 1_500)
		ah.append_pm_request_allocation_row(cl, req_name, 1_500)
		ah.normalize_funding_rows(cl)
		ah.run_allocation_validation(cl)
		row = cl.request_allocations[0]
		self.assertEqual(row.funding_source_type, "PM Request")
		self.assertFalse(row.pm_opening_advance)
