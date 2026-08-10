# Copyright (c) 2026, ERPNext Extensions contributors
"""v4.1.3: funding lifecycle status + close sync; workflow_state stays Waiting for Payment."""

from __future__ import annotations

import unittest

import frappe
from frappe.utils import cint, flt

from erpnext_extensions.petty_management.services.funding_service import close_pm_request
from erpnext_extensions.petty_management.services.request_action_policy import (
	build_pm_request_business_status_presentation,
	compute_pm_request_action_flags,
)
from erpnext_extensions.petty_management.services.workflow_utils import resolve_workflow_state_link
from erpnext_extensions.petty_management.tests import test_pm_clearance as tpm
from erpnext_extensions.petty_management.tests.test_pm_request_multi_pe import (
	_create_funding_pe,
	_ensure_pm_settings_bank,
	_new_submitted_request,
	_sync_funding_fields,
)


def _ws_title(name: str) -> str:
	ws = frappe.db.get_value("PM Request", name, "workflow_state")
	return frappe.db.get_value("Workflow State", ws, "workflow_state_name") or ws or ""


class TestPMRequestFundingStatusLifecycle(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")
		tpm._ensure_company_context()
		if not tpm.COMPANY:
			raise unittest.SkipTest("No company")
		_ensure_pm_settings_bank()
		cls.waiting = resolve_workflow_state_link("Waiting for Payment")

	def _row(self, name: str) -> dict:
		d = frappe.db.get_value(
			"PM Request",
			name,
			[
				"workflow_state",
				"status",
				"payment_status",
				"total_paid_amount",
				"remaining_to_pay",
				"is_closed",
			],
			as_dict=True,
		)
		d.workflow_title = _ws_title(name)
		return d

	def test_scenario_a_full_single_pe_keeps_workflow(self):
		emp = tpm._make_employee()
		tpm._make_holder(emp)
		req = _new_submitted_request(emp, 10_000)
		before = self._row(req)
		self.assertEqual(before.workflow_title, "Waiting for Payment")
		self.assertEqual(before.payment_status, "Not Paid")

		_create_funding_pe(req, 10_000)
		_sync_funding_fields(req)
		after = self._row(req)
		self.assertEqual(after.workflow_title, "Waiting for Payment")
		self.assertEqual(after.workflow_state, before.workflow_state)
		self.assertEqual(after.payment_status, "Paid")
		self.assertEqual(after.status, "Paid")
		self.assertAlmostEqual(flt(after.remaining_to_pay), 0.0, places=2)

		flags = compute_pm_request_action_flags(frappe.get_doc("PM Request", req))
		self.assertIn("Fully Funded", flags.get("business_status_headline") or "")
		self.assertFalse(flags["can_create_payment_entry"])
		blob = " ".join(flags.get("ui_messages") or [])
		self.assertIn("fully funded", blob.lower())

	def test_scenario_b_multi_pe_partial_then_full(self):
		emp = tpm._make_employee()
		tpm._make_holder(emp)
		req = _new_submitted_request(emp, 10_000)
		ws0 = frappe.db.get_value("PM Request", req, "workflow_state")

		_create_funding_pe(req, 4_000)
		_sync_funding_fields(req)
		mid = self._row(req)
		self.assertEqual(mid.payment_status, "Partially Paid")
		self.assertEqual(mid.status, "Waiting for Payment")
		self.assertAlmostEqual(flt(mid.remaining_to_pay), 6_000, places=2)
		self.assertEqual(mid.workflow_state, ws0)
		flags_mid = compute_pm_request_action_flags(frappe.get_doc("PM Request", req))
		self.assertEqual(flags_mid.get("business_status_headline"), "Partially Paid")

		_create_funding_pe(req, 6_000)
		_sync_funding_fields(req)
		end = self._row(req)
		self.assertEqual(end.payment_status, "Paid")
		self.assertEqual(end.status, "Paid")
		self.assertAlmostEqual(flt(end.remaining_to_pay), 0.0, places=2)
		self.assertEqual(end.workflow_state, ws0)

	def test_scenario_c_cancel_second_pe_reverts_partial(self):
		emp = tpm._make_employee()
		tpm._make_holder(emp)
		req = _new_submitted_request(emp, 10_000)
		ws0 = frappe.db.get_value("PM Request", req, "workflow_state")
		_create_funding_pe(req, 4_000)
		pe2 = _create_funding_pe(req, 6_000)
		_sync_funding_fields(req)
		self.assertEqual(self._row(req).payment_status, "Paid")

		frappe.get_doc("Payment Entry", pe2).cancel()
		frappe.db.commit()
		after = self._row(req)
		self.assertEqual(after.payment_status, "Partially Paid")
		self.assertEqual(after.status, "Waiting for Payment")
		self.assertAlmostEqual(flt(after.remaining_to_pay), 6_000, places=2)
		self.assertEqual(after.workflow_state, ws0)
		flags = compute_pm_request_action_flags(frappe.get_doc("PM Request", req))
		self.assertEqual(flags.get("business_status_headline"), "Partially Paid")
		self.assertNotIn("Fully Funded", flags.get("business_status_headline") or "")

	def test_scenario_d_close_sets_status_closed_immediately(self):
		emp = tpm._make_employee()
		tpm._make_holder(emp)
		req = _new_submitted_request(emp, 10_000)
		ws0 = frappe.db.get_value("PM Request", req, "workflow_state")
		_create_funding_pe(req, 10_000)
		_sync_funding_fields(req)

		close_pm_request(req)
		# No extra sync — assert immediately from DB
		row = self._row(req)
		self.assertEqual(cint(row.is_closed), 1)
		self.assertEqual(row.status, "Closed")
		self.assertEqual(row.payment_status, "Paid")
		self.assertEqual(row.workflow_state, ws0)
		self.assertEqual(_ws_title(req), "Waiting for Payment")

		pres = build_pm_request_business_status_presentation(frappe.get_doc("PM Request", req))
		self.assertEqual(pres.get("business_status_headline"), "Closed")
