# Copyright (c) 2026, Farbod Siyahpoosh and contributors
"""Dedicated over-allocation test (PI-free). Run with:

    bench --site development.localhost run-tests \\
        --module erpnext_extensions.petty_management.tests.test_pm_opening_advance_over_allocation \\
        --skip-before-tests
"""

from __future__ import annotations

import unittest

import frappe
from frappe.exceptions import ValidationError

import erpnext_extensions.petty_management.tests.test_pm_allocation_helpers as ah
import erpnext_extensions.petty_management.tests.test_pm_clearance as pm_ct


class TestPMOpeningAdvanceOverAllocation(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")
		ah.ensure_site_context()
		pm_ct._ensure_petty_account()

	def test_over_allocation_fails_on_allocation_validation(self):
		emp = pm_ct._make_employee()
		holder = pm_ct._make_holder(emp)
		oa = ah.make_submitted_opening(holder, 10_000, 0, reference_suffix="OVER-DEDICATED")
		cl = ah.build_clearance_for_allocation_validation(emp, holder, 11_000)
		ah.append_opening_allocation_row(cl, oa, 11_000)
		ah.normalize_funding_rows(cl)
		with self.assertRaises(ValidationError) as ctx:
			ah.run_allocation_validation(cl)
		self.assertIn("exceeds available opening balance", str(ctx.exception).lower())
