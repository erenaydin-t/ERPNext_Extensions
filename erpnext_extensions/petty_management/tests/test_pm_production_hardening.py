# Copyright (c) 2026, Farbod Siyahpoosh and contributors
# For license information, please see license.txt

"""Cancellation policy, reconciliation API shape, and duplicate funding guards.

**Import note:** Do not ``from test_pm_clearance import COMPANY, BANK_ACCOUNT`` — those are
bound once at import time (often empty). Always read ``tpm.COMPANY`` / ``tpm.BANK_ACCOUNT``
after ``tpm._ensure_company_context()`` so values match the live site.
"""

from __future__ import annotations

import unittest

import frappe
from frappe.exceptions import ValidationError
from frappe.utils import today

from erpnext_extensions.petty_management.tests import test_pm_clearance as tpm


def _clearance_pi(employee: str, pi, amount: float):
	cl = frappe.new_doc("PM Clearance")
	cl.company = tpm.COMPANY
	cl.employee = employee
	cl.transaction_date = today()
	cl.append(
		"details",
		{
			"settlement_type": "Purchase Invoice",
			"purchase_invoice": pi.name,
			"allocated_amount": amount,
			**tpm._pm_clearance_detail_policy_fields(),
		},
	)
	return cl


def _require_company_and_bank(test_case: unittest.TestCase) -> None:
	tpm._ensure_company_context()
	if not tpm.COMPANY:
		test_case.skipTest("No Company on site.")
	if not tpm.BANK_ACCOUNT:
		test_case.skipTest(f"No bank/cash account resolved for company {tpm.COMPANY!r}.")


class TestPMProductionHardening(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")
		tpm._ensure_company_context()
		if not tpm.COMPANY:
			raise unittest.SkipTest("No Company on site.")
		tpm._ensure_petty_account()

	def test_pm_request_cancel_blocked_when_referenced_on_submitted_clearance(self):
		_require_company_and_bank(self)

		from erpnext_extensions.petty_management.services.request_service import validate_request_cancel

		emp = tpm._make_employee()
		tpm._make_holder(emp)
		req_name, _pe = tpm._fund_pm_request(emp, 20_000.0)
		pi = tpm._make_pi_outstanding(5_000)
		pi.insert()
		pi.submit()
		cl = _clearance_pi(emp, pi, 5_000)
		cl.append("request_allocations", {"pm_request": req_name, "allocated_amount": 5_000})
		cl.insert()
		cl.submit()
		tpm._approve_pm_clearance_for_reservation(cl.name)

		doc = frappe.get_doc("PM Request", req_name)
		with self.assertRaises(ValidationError) as ctx:
			validate_request_cancel(doc)
		msg = str(ctx.exception)
		self.assertTrue("Clearance" in msg or "clearance" in msg.lower() or "Payment Entry" in msg)

	def test_clearance_cancel_blocked_when_settlement_je_submitted(self):
		_require_company_and_bank(self)

		mod = tpm._pm()
		approved = tpm._workflow_state_for("PM Clearance", "Approved")
		if not approved:
			self.skipTest("Active PM Clearance workflow with Approved state not found.")

		emp = tpm._make_employee()
		tpm._make_holder(emp)
		req_name, _pe = tpm._fund_pm_request(emp, 25_000.0)
		pi = tpm._make_pi_outstanding(10_000)
		pi.insert()
		pi.submit()
		cl = _clearance_pi(emp, pi, 10_000)
		cl.append("request_allocations", {"pm_request": req_name, "allocated_amount": 10_000})
		cl.insert()
		cl.submit()
		frappe.db.set_value("PM Clearance", cl.name, "workflow_state", approved, update_modified=False)
		mod.settle_petty_cash(cl.name)
		cl = frappe.get_doc("PM Clearance", cl.name)
		je = frappe.get_doc("Journal Entry", cl.journal_entry)
		if je.docstatus == 0:
			je.submit()
		cl.reload()
		from erpnext_extensions.petty_management.services.clearance_service import before_cancel_clearance

		with self.assertRaises(ValidationError) as ctx:
			before_cancel_clearance(cl)
		self.assertIn("Journal Entry", str(ctx.exception))

	def test_reconciliation_service_returns_structured_result(self):
		tpm._ensure_company_context()
		if not tpm.COMPANY:
			self.skipTest("No Company on site.")

		from erpnext_extensions.petty_management.services.reconciliation_service import reconcile

		res = reconcile(apply_safe_fixes=False, company=tpm.COMPANY)
		out = res.to_dict()
		self.assertIn("issues", out)
		self.assertIn("summary", out)
		self.assertIn("errors", out["summary"])

	def test_duplicate_active_payment_entry_reference_rejected(self):
		_require_company_and_bank(self)

		from erpnext_extensions.petty_management.services.request_service import (
			_build_payment_entry,
		)
		from erpnext_extensions.petty_management.services.request_service import (
			create_payment_entry as create_pm_pe,
		)

		appr = tpm._workflow_state_for("PM Request", "Finance Approved")
		if not appr:
			self.skipTest("Active PM Request workflow with Finance Approved state not found.")

		emp = tpm._make_employee()
		tpm._make_holder(emp)
		req = frappe.new_doc("PM Request")
		req.company = tpm.COMPANY
		req.employee = emp
		req.transaction_date = today()
		req.append("details", {"advance_amount": 5_000})
		req.insert()
		req.submit()
		tpm._finance_clear_pm_request(req.name)
		req.reload()

		existing = _build_payment_entry(req, tpm.BANK_ACCOUNT, 5_000)
		existing.insert(ignore_permissions=True)
		existing.db_set("reference_no", req.name, update_modified=False)

		with self.assertRaises(ValidationError) as ctx:
			create_pm_pe(req.name)
		msg = str(ctx.exception).lower()
		self.assertTrue(
			"exceeds" in msg
			or "over-funding" in msg
			or "remaining" in msg
			or "draft" in msg
			or "payment entry" in msg
		)

	def test_pm_clearance_rapid_insert_names_unique(self):
		"""Monthly naming series must not block concurrent/rapid saves (no per-employee Series row)."""
		_require_company_and_bank(self)
		emp = tpm._make_employee()
		tpm._make_holder(emp)
		req_name, _pe = tpm._fund_pm_request(emp, 10_000.0)
		pi = tpm._make_pi_outstanding(1_000)
		pi.insert()
		pi.submit()
		names = []
		for _ in range(3):
			cl = _clearance_pi(emp, pi, 500)
			cl.append("request_allocations", {"pm_request": req_name, "allocated_amount": 500})
			cl.insert()
			names.append(cl.name)
			frappe.db.commit()
		self.assertEqual(len(names), len(set(names)))
		for name in names:
			self.assertTrue(name.startswith("CLR-"), msg=name)

	def test_second_create_payment_entry_rejected_when_already_funded(self):
		_require_company_and_bank(self)

		from erpnext_extensions.petty_management.services.request_service import create_payment_entry

		appr = tpm._workflow_state_for("PM Request", "Finance Approved")
		if not appr:
			self.skipTest("Active PM Request workflow with Finance Approved state not found.")

		emp = tpm._make_employee()
		tpm._make_holder(emp)
		req_name, _pe = tpm._fund_pm_request(emp, 8_000.0)

		with self.assertRaises(ValidationError) as ctx:
			create_payment_entry(req_name)
		msg = str(ctx.exception).lower()
		self.assertTrue(
			"fully funded" in msg or "funded" in msg or "payment entry" in msg or "already" in msg
		)


if __name__ == "__main__":
	unittest.main()
