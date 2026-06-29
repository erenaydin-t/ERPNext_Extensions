# Copyright (c) 2026, Farbod Siyahpoosh and contributors
"""Integration: 100k → 40k + 30k PE → close → clearance → settle → cancel chain."""

from __future__ import annotations

import unittest

import frappe
from frappe.utils import flt, today

from erpnext_extensions.petty_management.tests import test_pm_clearance as tpm
from erpnext_extensions.petty_management.tests.test_pm_request_multi_pe import (
	_approve_pm_request,
	_close_pm_request,
	_create_funding_pe,
	_new_submitted_request,
	_require_site_ready,
	_sync_funding_fields,
)


class TestMultiPeIntegrationFlow(unittest.TestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		_require_site_ready(self)

	def test_partial_fund_close_clearance_settle_and_roll_back(self):
		from erpnext_extensions.petty_management.doctype.pm_clearance import pm_clearance as mod
		from erpnext_extensions.petty_management.services.allocation_service import (
			get_pm_request_available_amount,
			get_pm_request_paid_amount,
			sum_prior_pm_request_allocations,
		)

		emp = None
		for _attempt in range(5):
			try:
				emp = tpm._make_employee()
				break
			except frappe.QueryDeadlockError:
				frappe.db.rollback()
		if not emp:
			emp = tpm._make_employee()
		tpm._make_holder(emp)
		req = _new_submitted_request(emp, 100_000)
		_create_funding_pe(req, 40_000)
		_create_funding_pe(req, 30_000)
		_sync_funding_fields(req)

		paid_before_close = flt(get_pm_request_paid_amount(req))
		avail_before_close = flt(get_pm_request_available_amount(req))
		_close_pm_request(req, close_reason="Budget Limitation")
		self.assertAlmostEqual(flt(get_pm_request_paid_amount(req)), paid_before_close, places=2)
		self.assertAlmostEqual(flt(get_pm_request_available_amount(req)), avail_before_close, places=2)

		pi = tpm._make_pi_outstanding(15_000)
		pi.insert()
		pi.submit()
		cl = frappe.new_doc("PM Clearance")
		cl.company = tpm.COMPANY
		cl.employee = emp
		cl.transaction_date = today()
		cl.append(
			"details",
			{
				"settlement_type": "Purchase Invoice",
				"purchase_invoice": pi.name,
				"allocated_amount": 15_000,
				**tpm._pm_clearance_detail_policy_fields(),
			},
		)
		cl.append("request_allocations", {"pm_request": req, "allocated_amount": 15_000})
		cl.insert()
		cl.submit()
		tpm._approve_pm_clearance_for_reservation(cl.name)
		self.assertAlmostEqual(flt(sum_prior_pm_request_allocations(req, None)), 15_000, places=2)

		cl_appr = tpm._workflow_state_for("PM Clearance", "Approved")
		if cl_appr:
			frappe.db.set_value("PM Clearance", cl.name, "workflow_state", cl_appr, update_modified=False)
		s1 = mod.settle_petty_cash(cl.name)
		je_name = s1.get("journal_entry")
		self.assertTrue(je_name)

		avail_after_settle = flt(get_pm_request_available_amount(req))
		self.assertAlmostEqual(avail_after_settle, paid_before_close - 15_000, places=2)

		je = frappe.get_doc("Journal Entry", je_name)
		if je.docstatus == 0:
			je.submit()
			je.reload()
		je.cancel()

		cl.reload()
		cl.cancel()
		frappe.db.commit()

		self.assertAlmostEqual(flt(sum_prior_pm_request_allocations(req, None)), 0, places=2)
		self.assertAlmostEqual(flt(get_pm_request_available_amount(req)), paid_before_close, places=2)

	def test_three_partial_payment_entries_aggregate(self):
		from erpnext_extensions.petty_management.services.allocation_service import get_pm_request_paid_amount

		emp = None
		for _attempt in range(5):
			try:
				emp = tpm._make_employee()
				break
			except frappe.QueryDeadlockError:
				frappe.db.rollback()
		if not emp:
			emp = tpm._make_employee()
		tpm._make_holder(emp)
		req = _new_submitted_request(emp, 90_000)
		_create_funding_pe(req, 20_000)
		_create_funding_pe(req, 25_000)
		_create_funding_pe(req, 15_000)
		_sync_funding_fields(req)
		doc = frappe.get_doc("PM Request", req)
		self.assertAlmostEqual(flt(doc.total_paid_amount), 60_000, places=2)
		self.assertAlmostEqual(flt(doc.remaining_to_pay), 30_000, places=2)
		self.assertEqual(doc.payment_status, "Partially Paid")
		self.assertAlmostEqual(get_pm_request_paid_amount(req), 60_000, places=2)

	def test_get_pm_request_payment_entries_via_frappe_call(self):
		emp = tpm._make_employee()
		tpm._make_holder(emp)
		req = _new_submitted_request(emp, 25_000)
		_create_funding_pe(req, 7_000)
		frappe.set_user("Administrator")
		rows = frappe.call(
			"erpnext_extensions.petty_management.doctype.pm_request.pm_request.get_pm_request_payment_entries",
			pm_request=req,
		)
		self.assertIsInstance(rows, dict)
		entries = rows.get("payment_entries") or []
		self.assertEqual(len(entries), 1)
		self.assertAlmostEqual(float(entries[0]["amount"]), 7_000, places=2)
		self.assertTrue(rows.get("response_version_id"))


if __name__ == "__main__":
	unittest.main()
