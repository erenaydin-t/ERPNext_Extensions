# Copyright (c) 2026, Farbod Siyahpoosh and contributors
"""Settle-time availability: current clearance must not double-count its own reservation."""

from __future__ import annotations

import unittest

import frappe
from frappe.exceptions import ValidationError
from frappe.utils import flt

import erpnext_extensions.petty_management.tests.test_pm_clearance as pm_ct
from erpnext_extensions.petty_management.services.allocation_service import (
	get_pm_request_available_amount,
	sum_prior_pm_request_allocations,
)
from erpnext_extensions.petty_management.services.clearance_service import validate_clearance
from erpnext_extensions.petty_management.services.holder_service import (
	get_holder_balances,
	sync_clearance_holder_fields,
)
from erpnext_extensions.petty_management.tests.test_pm_allocation_helpers import (
	append_opening_allocation_row,
	build_clearance_for_allocation_validation,
	make_submitted_opening,
	run_allocation_validation,
)


def _pm():
	return pm_ct._pm()


def _workflow_approved():
	return pm_ct._workflow_state_for("PM Clearance", "Approved")


class TestPMClearanceSettleAvailability(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		pm_ct._ensure_company_context()
		if not pm_ct.COMPANY:
			raise unittest.SkipTest("No Company on site")

	def setUp(self):
		self._created: list[tuple[str, str]] = []

	def tearDown(self):
		for dt, name in reversed(self._created):
			try:
				if frappe.db.exists(dt, name):
					doc = frappe.get_doc(dt, name)
					if doc.docstatus == 1:
						doc.cancel()
					elif doc.docstatus == 0:
						doc.delete()
			except Exception:
				pass
		frappe.db.commit()

	def _track(self, dt: str, name: str) -> None:
		self._created.append((dt, name))

	def test_holder_balance_excludes_own_submitted_clearance(self):
		"""Root cause: without exclude, holder funded_available is 0 while this clearance owns the reservation."""
		emp = pm_ct._make_employee()
		self._track("Employee", emp)
		pm_ct._make_holder(emp)
		holder = frappe.db.get_value("PM Holder", {"employee": emp, "company": pm_ct.COMPANY}, "name")
		req_name, _pe = pm_ct._fund_pm_request(emp, 10_000.0)
		self._track("PM Request", req_name)

		pi = pm_ct._make_pi_outstanding(10_000)
		pi.insert()
		pi.submit()
		self._track("Purchase Invoice", pi.name)

		cl = pm_ct.TestPMClearanceAllocation()._base_clearance(emp, pi, 10_000)
		cl.append("request_allocations", {"pm_request": req_name, "allocated_amount": 10_000})
		cl.insert()
		cl.submit()
		self._track("PM Clearance", cl.name)
		pm_ct._approve_pm_clearance_for_reservation(cl.name)
		approved = _workflow_approved()
		if approved:
			frappe.db.set_value("PM Clearance", cl.name, "workflow_state", approved, update_modified=False)

		without = get_holder_balances(holder)
		with_excl = get_holder_balances(holder, exclude_clearance_name=cl.name)
		self.assertLess(flt(without.funded_available_amount), 1e-3)
		self.assertGreaterEqual(flt(with_excl.funded_available_amount), 10_000.0 - 1e-3)
		self.assertGreaterEqual(flt(sum_prior_pm_request_allocations(req_name, cl.name)), 0)
		self.assertGreaterEqual(flt(sum_prior_pm_request_allocations(req_name, None)), 10_000.0 - 1e-3)

		doc = frappe.get_doc("PM Clearance", cl.name)
		sync_clearance_holder_fields(doc)
		self.assertGreaterEqual(flt(doc.total_available), 10_000.0 - 1e-3)
		validate_clearance(doc)

	def test_pm_request_full_allocation_settle_and_duplicate_settle(self):
		mod = _pm()
		approved = _workflow_approved()
		if not approved:
			self.skipTest("PM Clearance Approved workflow state missing")

		emp = pm_ct._make_employee()
		self._track("Employee", emp)
		pm_ct._make_holder(emp)
		req_name, _pe = pm_ct._fund_pm_request(emp, 10_000.0)
		self._track("PM Request", req_name)

		pi = pm_ct._make_pi_outstanding(10_000)
		pi.insert()
		pi.submit()
		self._track("Purchase Invoice", pi.name)

		cl = pm_ct.TestPMClearanceAllocation()._base_clearance(emp, pi, 10_000)
		cl.append("request_allocations", {"pm_request": req_name, "allocated_amount": 10_000})
		cl.insert()
		cl.submit()
		self._track("PM Clearance", cl.name)
		pm_ct._approve_pm_clearance_for_reservation(cl.name)
		frappe.db.set_value("PM Clearance", cl.name, "workflow_state", approved, update_modified=False)

		first = mod.settle_petty_cash(cl.name)
		self._track("Journal Entry", first["journal_entry"])
		second = mod.settle_petty_cash(cl.name)
		self.assertEqual(first["journal_entry"], second["journal_entry"])

	def test_second_clearance_exceeding_pm_request_remaining_fails(self):
		emp = pm_ct._make_employee()
		self._track("Employee", emp)
		pm_ct._make_holder(emp)
		req_name, _pe = pm_ct._fund_pm_request(emp, 5_000.0)
		self._track("PM Request", req_name)

		pi1 = pm_ct._make_pi_outstanding(5_000)
		pi1.insert()
		pi1.submit()
		self._track("Purchase Invoice", pi1.name)
		pi2 = pm_ct._make_pi_outstanding(1_000)
		pi2.insert()
		pi2.submit()
		self._track("Purchase Invoice", pi2.name)

		cl1 = pm_ct.TestPMClearanceAllocation()._base_clearance(emp, pi1, 5_000)
		cl1.append("request_allocations", {"pm_request": req_name, "allocated_amount": 5_000})
		cl1.insert()
		cl1.submit()
		self._track("PM Clearance", cl1.name)
		pm_ct._approve_pm_clearance_for_reservation(cl1.name)

		cl2 = pm_ct.TestPMClearanceAllocation()._base_clearance(emp, pi2, 1_000)
		cl2.append("request_allocations", {"pm_request": req_name, "allocated_amount": 1_000})
		with self.assertRaises(ValidationError):
			cl2.insert()

	def test_opening_advance_submitted_clearance_settle_policy_excludes_own_row(self):
		approved = _workflow_approved()
		if not approved:
			self.skipTest("PM Clearance Approved workflow state missing")
		mod = _pm()

		emp = pm_ct._make_employee()
		self._track("Employee", emp)
		holder = pm_ct._make_holder(emp)
		oa_name = make_submitted_opening(holder, 10_000.0, reference_suffix="SETTLE-AVAIL-OA")
		self._track("PM Opening Advance", oa_name)

		pi = pm_ct._make_pi_outstanding(4_000)
		pi.insert()
		pi.submit()
		self._track("Purchase Invoice", pi.name)

		cl = pm_ct.TestPMClearanceAllocation()._base_clearance(emp, pi, 4_000)
		cl.append(
			"request_allocations",
			{
				"funding_source_type": "PM Opening Advance",
				"pm_opening_advance": oa_name,
				"allocated_amount": 4_000,
			},
		)
		cl.insert()
		cl.submit()
		self._track("PM Clearance", cl.name)
		pm_ct._approve_pm_clearance_for_reservation(cl.name)
		frappe.db.set_value("PM Clearance", cl.name, "workflow_state", approved, update_modified=False)

		out = mod.settle_petty_cash(cl.name)
		self._track("Journal Entry", out["journal_entry"])
		self.assertTrue(out.get("journal_entry"))

	def test_draft_over_allocation_still_blocked(self):
		pm_ct._ensure_company_context()
		emp = pm_ct._make_employee()
		self._track("Employee", emp)
		holder = pm_ct._make_holder(emp)
		oa_name = make_submitted_opening(holder, 5_000.0, reference_suffix="SETTLE-AVAIL-OVER")
		self._track("PM Opening Advance", oa_name)

		cl = build_clearance_for_allocation_validation(emp, holder, 10_001.0)
		append_opening_allocation_row(cl, oa_name, 10_001.0)
		with self.assertRaises(ValidationError):
			run_allocation_validation(cl)


if __name__ == "__main__":
	unittest.main()
