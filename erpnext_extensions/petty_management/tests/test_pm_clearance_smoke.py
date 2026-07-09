# Copyright (c) 2026, Farbod Siyahpoosh and contributors
"""Backend smoke tests: PM Request flow, PM Opening Advance flow, mixed funding."""

from __future__ import annotations

import unittest

import frappe
from frappe.utils import flt, today

from erpnext_extensions.petty_management.services.opening_advance_service import (
	get_opening_advance_available_amount,
)
import erpnext_extensions.petty_management.tests.test_pm_clearance as pm_ct


def _pm():
	from erpnext_extensions.petty_management.doctype.pm_clearance import pm_clearance as mod

	return mod


def _submit_pi(pi):
	try:
		pi.insert(ignore_permissions=True)
		pi.submit()
	except TypeError as exc:
		if "do_not_round_fields" in str(exc):
			raise unittest.SkipTest("Purchase Invoice submit incompatible with this Frappe version") from exc
		raise


class TestPMClearanceSmokeFlows(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")
		pm_ct._ensure_company_context()
		if not pm_ct.COMPANY:
			raise unittest.SkipTest("No Company on site")

	def setUp(self):
		frappe.set_user("Administrator")
		self._cleanup: list[tuple[str, str]] = []

	def tearDown(self):
		for doctype, name in reversed(self._cleanup):
			try:
				if not frappe.db.exists(doctype, name):
					continue
				doc = frappe.get_doc(doctype, name)
				if doc.docstatus == 1:
					doc.cancel()
				frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
			except Exception:
				pass
		frappe.db.commit()

	def _track(self, doctype: str, name: str) -> None:
		self._cleanup.append((doctype, name))

	def test_flow_a_pm_request_settle_and_cancel(self):
		mod = _pm()
		approved = pm_ct._workflow_state_for("PM Clearance", "Approved")
		if not approved:
			raise unittest.SkipTest("PM Clearance workflow Approved state not configured")
		emp = pm_ct._make_employee()
		self._track("Employee", emp)
		pm_ct._make_holder(emp)
		req_name, pe_name = pm_ct._fund_pm_request(emp, 20_000.0)
		self._track("PM Request", req_name)
		self._track("Payment Entry", pe_name)
		pi = pm_ct._make_pi_outstanding(5_000)
		_submit_pi(pi)
		self._track("Purchase Invoice", pi.name)
		cl = pm_ct._lifecycle_base_clearance(emp, pi, 5_000)
		cl.append("request_allocations", {"pm_request": req_name, "allocated_amount": 5_000})
		cl.insert(ignore_permissions=True)
		self._track("PM Clearance", cl.name)
		mod.preview_pm_clearance_settlement(pm_clearance=cl.name)
		cl.submit()
		pm_ct._approve_pm_clearance_for_reservation(cl.name)
		frappe.db.set_value("PM Clearance", cl.name, "workflow_state", approved, update_modified=False)
		out = mod.settle_petty_cash(cl.name)
		je_name = out["journal_entry"]
		self._track("Journal Entry", je_name)
		je = frappe.get_doc("Journal Entry", je_name)
		if je.docstatus == 0:
			je.submit()
		je.cancel()
		cl = frappe.get_doc("PM Clearance", cl.name)
		cl.reload()
		cl.cancel()

	def test_flow_b_opening_advance_settle_and_restore(self):
		mod = _pm()
		approved = pm_ct._workflow_state_for("PM Clearance", "Approved")
		if not approved:
			raise unittest.SkipTest("PM Clearance workflow Approved state not configured")
		emp = pm_ct._make_employee()
		self._track("Employee", emp)
		holder = pm_ct._make_holder(emp)
		oa = frappe.new_doc("PM Opening Advance")
		oa.holder = holder
		oa.opening_date = today()
		oa.opening_source_type = "Opening Balance"
		oa.opening_advance_amount = 12_000
		oa.previously_settled_before_migration = 4_000
		oa.insert(ignore_permissions=True)
		oa.submit()
		self._track("PM Opening Advance", oa.name)
		self.assertEqual(get_opening_advance_available_amount(oa.name), 8_000)
		pi = pm_ct._make_pi_outstanding(4_000)
		_submit_pi(pi)
		self._track("Purchase Invoice", pi.name)
		cl = pm_ct._lifecycle_base_clearance(emp, pi, 4_000)
		cl.append(
			"request_allocations",
			{
				"funding_source_type": "PM Opening Advance",
				"pm_opening_advance": oa.name,
				"allocated_amount": 4_000,
			},
		)
		cl.insert(ignore_permissions=True)
		self._track("PM Clearance", cl.name)
		mod.preview_pm_clearance_settlement(pm_clearance=cl.name)
		cl.submit()
		pm_ct._approve_pm_clearance_for_reservation(cl.name)
		frappe.db.set_value("PM Clearance", cl.name, "workflow_state", approved, update_modified=False)
		self.assertEqual(get_opening_advance_available_amount(oa.name), 4_000)
		out = mod.settle_petty_cash(cl.name)
		je_name = out["journal_entry"]
		self._track("Journal Entry", je_name)
		je = frappe.get_doc("Journal Entry", je_name)
		if je.docstatus == 0:
			je.submit()
		je.cancel()
		cl = frappe.get_doc("PM Clearance", cl.name)
		cl.reload()
		cl.cancel()
		self.assertEqual(get_opening_advance_available_amount(oa.name), 8_000)

	def test_flow_c_mixed_funding_save_and_cancel(self):
		emp = pm_ct._make_employee()
		self._track("Employee", emp)
		holder = pm_ct._make_holder(emp)
		req_name, _pe = pm_ct._fund_pm_request(emp, 10_000.0)
		self._track("PM Request", req_name)
		oa = frappe.new_doc("PM Opening Advance")
		oa.holder = holder
		oa.opening_date = today()
		oa.opening_source_type = "Opening Balance"
		oa.opening_advance_amount = 10_000
		oa.insert(ignore_permissions=True)
		oa.submit()
		self._track("PM Opening Advance", oa.name)
		from erpnext_extensions.petty_management.services.opening_advance_service import (
			get_opening_advance_available_amount,
		)
		from erpnext_extensions.petty_management.services.allocation_service import (
			get_pm_request_available_amount,
		)

		open_before = get_opening_advance_available_amount(oa.name)
		req_before = get_pm_request_available_amount(req_name)
		pi = pm_ct._make_pi_outstanding(6_000)
		_submit_pi(pi)
		self._track("Purchase Invoice", pi.name)
		cl = pm_ct._lifecycle_base_clearance(emp, pi, 6_000)
		cl.append(
			"request_allocations",
			{"funding_source_type": "PM Request", "pm_request": req_name, "allocated_amount": 3_000},
		)
		cl.append(
			"request_allocations",
			{
				"funding_source_type": "PM Opening Advance",
				"pm_opening_advance": oa.name,
				"allocated_amount": 3_000,
			},
		)
		cl.insert(ignore_permissions=True)
		self._track("PM Clearance", cl.name)
		cl.submit()
		pm_ct._approve_pm_clearance_for_reservation(cl.name)
		self.assertEqual(get_pm_request_available_amount(req_name), flt(req_before) - 3_000)
		self.assertEqual(get_opening_advance_available_amount(oa.name), flt(open_before) - 3_000)
		frappe.db.set_value(
			"PM Clearance",
			cl.name,
			{"docstatus": 2, "status": "Cancelled"},
			update_modified=False,
		)
		self.assertEqual(get_pm_request_available_amount(req_name), req_before)
		self.assertEqual(get_opening_advance_available_amount(oa.name), open_before)
