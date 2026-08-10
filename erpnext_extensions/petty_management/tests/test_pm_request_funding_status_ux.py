# Copyright (c) 2026, ERPNext Extensions contributors
"""v4.1.3 Option A: Finance Approved workflow + business status lifecycle."""

from __future__ import annotations

import unittest

import frappe
from frappe.utils import cint, flt

from erpnext_extensions.petty_management.services.business_status_service import (
	REQ_WORKFLOW_FINANCE_APPROVED,
	request_is_finance_cleared,
	sync_pm_request_business_status,
	workflow_title_is_finance_cleared,
)
from erpnext_extensions.petty_management.services.funding_service import close_pm_request
from erpnext_extensions.petty_management.services.request_action_policy import (
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


class TestPMRequestFinanceApprovedArchitecture(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")
		tpm._ensure_company_context()
		if not tpm.COMPANY:
			raise unittest.SkipTest("No company")
		_ensure_pm_settings_bank()
		cls.finance_approved = resolve_workflow_state_link(REQ_WORKFLOW_FINANCE_APPROVED)

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

	def test_helper_accepts_finance_approved_and_legacy_waiting(self):
		self.assertTrue(workflow_title_is_finance_cleared("Finance Approved"))
		self.assertTrue(workflow_title_is_finance_cleared("Waiting for Payment"))
		self.assertTrue(workflow_title_is_finance_cleared("Approved"))
		self.assertFalse(workflow_title_is_finance_cleared("Pending Finance Approval"))

		doc = frappe._dict(
			workflow_state=resolve_workflow_state_link("Waiting for Payment"),
			status="Waiting for Payment",
			payment_status="Not Paid",
			is_closed=0,
			docstatus=1,
		)
		self.assertTrue(request_is_finance_cleared(doc))
		doc.workflow_state = self.finance_approved
		self.assertTrue(request_is_finance_cleared(doc))

	def test_scenario_finance_approval_business_waiting(self):
		emp = tpm._make_employee()
		tpm._make_holder(emp)
		req = _new_submitted_request(emp, 10_000)
		row = self._row(req)
		self.assertEqual(row.workflow_title, "Finance Approved")
		self.assertEqual(row.status, "Waiting for Payment")
		self.assertEqual(row.payment_status, "Not Paid")

	def test_scenario_partial_then_full_then_cancel(self):
		emp = tpm._make_employee()
		tpm._make_holder(emp)
		req = _new_submitted_request(emp, 10_000)
		ws0 = frappe.db.get_value("PM Request", req, "workflow_state")

		_create_funding_pe(req, 4_000)
		_sync_funding_fields(req)
		mid = self._row(req)
		self.assertEqual(mid.workflow_state, ws0)
		self.assertEqual(mid.payment_status, "Partially Paid")
		self.assertEqual(mid.status, "Partially Paid")
		self.assertAlmostEqual(flt(mid.remaining_to_pay), 6_000, places=2)

		pe2 = _create_funding_pe(req, 6_000)
		_sync_funding_fields(req)
		full = self._row(req)
		self.assertEqual(full.workflow_state, ws0)
		self.assertEqual(full.payment_status, "Paid")
		self.assertEqual(full.status, "Paid")
		self.assertAlmostEqual(flt(full.remaining_to_pay), 0.0, places=2)

		frappe.get_doc("Payment Entry", pe2).cancel()
		frappe.db.commit()
		after = self._row(req)
		self.assertEqual(after.workflow_state, ws0)
		self.assertEqual(after.payment_status, "Partially Paid")
		self.assertEqual(after.status, "Partially Paid")
		self.assertAlmostEqual(flt(after.remaining_to_pay), 6_000, places=2)

	def test_scenario_close_keeps_workflow_and_payment_status(self):
		emp = tpm._make_employee()
		tpm._make_holder(emp)
		req = _new_submitted_request(emp, 10_000)
		ws0 = frappe.db.get_value("PM Request", req, "workflow_state")
		_create_funding_pe(req, 10_000)
		_sync_funding_fields(req)
		close_pm_request(req)
		row = self._row(req)
		self.assertEqual(cint(row.is_closed), 1)
		self.assertEqual(row.status, "Closed")
		self.assertEqual(row.payment_status, "Paid")
		self.assertEqual(row.workflow_state, ws0)
		self.assertEqual(row.workflow_title, "Finance Approved")

	def test_sync_maps_pending_workflow_to_specific_status(self):
		doc = frappe._dict(
			docstatus=1,
			workflow_state=resolve_workflow_state_link("Pending CEO Approval"),
			payment_status="Not Paid",
			is_closed=0,
			status="",
		)
		self.assertEqual(sync_pm_request_business_status(doc), "Pending CEO Approval")

	def test_flags_do_not_contradict_finance_approved_with_paid(self):
		emp = tpm._make_employee()
		tpm._make_holder(emp)
		req = _new_submitted_request(emp, 5_000)
		_create_funding_pe(req, 5_000)
		_sync_funding_fields(req)
		flags = compute_pm_request_action_flags(frappe.get_doc("PM Request", req))
		self.assertEqual(flags.get("workflow_state_title"), "Finance Approved")
		self.assertEqual(flags.get("status"), "Paid")
		self.assertEqual(flags.get("payment_status"), "Paid")
		self.assertFalse(flags.get("can_create_payment_entry"))
		# No competing "Waiting for Payment" business headline after Option A
		self.assertNotIn("Waiting for Payment", flags.get("business_status_headline") or "")
