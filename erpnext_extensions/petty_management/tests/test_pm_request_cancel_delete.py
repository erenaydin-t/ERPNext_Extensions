# Copyright (c) 2026, ERPNext Extensions contributors
"""v4.6.8 — PM Request cancel / delete eligibility.

Run::

	bench --site development.localhost run-tests \\
		--module erpnext_extensions.petty_management.tests.test_pm_request_cancel_delete \\
		--skip-before-tests
"""

from __future__ import annotations

import unittest

import frappe
from frappe.exceptions import ValidationError
from frappe.utils import cint, flt, today

from erpnext_extensions.petty_management.services.request_lifecycle_eligibility import (
	assert_pm_request_cancel_allowed,
	assert_pm_request_delete_allowed,
	get_pm_request_cancel_blockers,
	get_pm_request_delete_blockers,
)
from erpnext_extensions.petty_management.tests import test_pm_clearance as tpm
from erpnext_extensions.petty_management.tests.test_pm_request_multi_pe import (
	_create_funding_pe,
	_new_submitted_request,
	_require_site_ready,
	_sync_funding_fields,
)


def _draft_pe(req: str, amount: float) -> str:
	from erpnext_extensions.petty_management.services import request_service as rs

	pe_name = rs.create_payment_entry(req, paid_amount=amount)
	pe = frappe.get_doc("Payment Entry", pe_name)
	if pe.docstatus != 0:
		# Site may auto-submit; cancel and recreate is messy — force draft via new PE amount split
		frappe.throw(f"Expected draft PE, got docstatus={pe.docstatus}")
	return pe_name


def _make_clearance(emp: str, req: str, amount: float, *, submit: bool = False, approve: bool = False):
	pi = tpm._make_pi_outstanding(amount)
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
			"allocated_amount": amount,
			**tpm._pm_clearance_detail_policy_fields(),
		},
	)
	cl.append("request_allocations", {"pm_request": req, "allocated_amount": amount})
	cl.insert()
	if submit:
		cl.submit()
	if approve:
		tpm._approve_pm_clearance_for_reservation(cl.name)
	return cl.name


def _set_clearance_status(name: str, status: str, docstatus: int | None = None):
	vals = {"status": status}
	if docstatus is not None:
		vals["docstatus"] = docstatus
	frappe.db.set_value("PM Clearance", name, vals, update_modified=False)


def _force_clearance_cancelled(name: str):
	"""Mark Clearance + child rows cancelled (Frappe back-link uses child docstatus)."""
	frappe.db.set_value(
		"PM Clearance", name, {"docstatus": 2, "status": "Cancelled"}, update_modified=False
	)
	for table in ("PM Clearance Request Allocation", "PM Clearance Detail"):
		if frappe.db.table_exists(f"tab{table}"):
			frappe.db.sql(
				f"UPDATE `tab{table}` SET docstatus=2 WHERE parent=%s AND parenttype='PM Clearance'",
				(name,),
			)


class TestPmRequestCancelEligibility(unittest.TestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		_require_site_ready(self)

	def test_cancel_no_pe(self):
		emp = tpm._make_employee()
		tpm._make_holder(emp)
		req = _new_submitted_request(emp, 10_000)
		ws = frappe.db.get_value("PM Request", req, "workflow_state")
		approvers = frappe.db.get_value(
			"PM Request", req, ["manager_approver", "ceo_approver", "finance_approver"], as_dict=True
		)
		assert_pm_request_cancel_allowed(req)
		frappe.get_doc("PM Request", req).cancel()
		frappe.db.commit()
		row = frappe.db.get_value(
			"PM Request", req, ["docstatus", "status", "workflow_state"], as_dict=True
		)
		self.assertEqual(cint(row.docstatus), 2)
		self.assertEqual(row.status, "Cancelled")
		self.assertEqual(row.workflow_state, ws)
		after = frappe.db.get_value(
			"PM Request", req, ["manager_approver", "ceo_approver", "finance_approver"], as_dict=True
		)
		self.assertEqual(after, approvers)

	def test_cancel_blocked_draft_pe(self):
		emp = tpm._make_employee()
		tpm._make_holder(emp)
		req = _new_submitted_request(emp, 20_000)
		try:
			pe = _draft_pe(req, 5_000)
		except Exception:
			self.skipTest("Could not create draft PE (auto-submit?)")
		with self.assertRaises(ValidationError) as ctx:
			assert_pm_request_cancel_allowed(req)
		self.assertIn("draft", str(ctx.exception).lower())
		self.assertTrue(frappe.db.exists("Payment Entry", pe))

	def test_cancel_blocked_submitted_pe(self):
		emp = tpm._make_employee()
		tpm._make_holder(emp)
		req = _new_submitted_request(emp, 15_000)
		_create_funding_pe(req, 15_000)
		_sync_funding_fields(req)
		with self.assertRaises(ValidationError) as ctx:
			frappe.get_doc("PM Request", req).cancel()
		self.assertIn("submitted", str(ctx.exception).lower())

	def test_cancel_after_all_pe_cancelled(self):
		emp = tpm._make_employee()
		tpm._make_holder(emp)
		req = _new_submitted_request(emp, 12_000)
		pe = _create_funding_pe(req, 12_000)
		_sync_funding_fields(req)
		frappe.get_doc("Payment Entry", pe).cancel()
		_sync_funding_fields(req)
		self.assertAlmostEqual(flt(frappe.db.get_value("PM Request", req, "total_paid_amount")), 0)
		assert_pm_request_cancel_allowed(req)
		frappe.get_doc("PM Request", req).cancel()
		self.assertEqual(cint(frappe.db.get_value("PM Request", req, "docstatus")), 2)

	def test_cancel_multi_pe_partial_blocks(self):
		emp = tpm._make_employee()
		tpm._make_holder(emp)
		req = _new_submitted_request(emp, 100_000)
		pe1 = _create_funding_pe(req, 40_000)
		_create_funding_pe(req, 60_000)
		_sync_funding_fields(req)
		frappe.get_doc("Payment Entry", pe1).cancel()
		_sync_funding_fields(req)
		# still partially funded
		self.assertGreater(flt(frappe.db.get_value("PM Request", req, "total_paid_amount")), 0)
		with self.assertRaises(ValidationError):
			assert_pm_request_cancel_allowed(req)

	def test_cancel_blocked_draft_clearance(self):
		emp = tpm._make_employee()
		tpm._make_holder(emp)
		req = _new_submitted_request(emp, 30_000)
		pe = _create_funding_pe(req, 30_000)
		_sync_funding_fields(req)
		_make_clearance(emp, req, 5_000, submit=False)
		frappe.get_doc("Payment Entry", pe).cancel()
		_sync_funding_fields(req)
		with self.assertRaises(ValidationError) as ctx:
			assert_pm_request_cancel_allowed(req)
		self.assertIn("clearance", str(ctx.exception).lower())

	def test_cancel_blocked_approved_clearance(self):
		emp = tpm._make_employee()
		tpm._make_holder(emp)
		req = _new_submitted_request(emp, 40_000)
		pe = _create_funding_pe(req, 40_000)
		_sync_funding_fields(req)
		cl = _make_clearance(emp, req, 10_000, submit=False)
		frappe.get_doc("Payment Entry", pe).cancel()
		_sync_funding_fields(req)
		frappe.db.set_value(
			"PM Clearance", cl, {"docstatus": 1, "status": "Approved"}, update_modified=False
		)
		with self.assertRaises(ValidationError) as ctx:
			assert_pm_request_cancel_allowed(req)
		self.assertIn("clearance", str(ctx.exception).lower())

	def test_cancel_blocked_pending_clearance(self):
		emp = tpm._make_employee()
		tpm._make_holder(emp)
		req = _new_submitted_request(emp, 35_000)
		pe = _create_funding_pe(req, 35_000)
		_sync_funding_fields(req)
		cl = _make_clearance(emp, req, 4_000, submit=True)
		_set_clearance_status(cl, "Pending Finance Review")
		frappe.get_doc("Payment Entry", pe).cancel()
		_sync_funding_fields(req)
		with self.assertRaises(ValidationError) as ctx:
			assert_pm_request_cancel_allowed(req)
		self.assertIn("clearance", str(ctx.exception).lower())

	def test_cancel_blocked_settled_clearance(self):
		emp = tpm._make_employee()
		tpm._make_holder(emp)
		req = _new_submitted_request(emp, 36_000)
		pe = _create_funding_pe(req, 36_000)
		_sync_funding_fields(req)
		# Draft clearance so PE can cancel (Settled reserves funding and blocks PE cancel).
		cl = _make_clearance(emp, req, 4_000, submit=False)
		frappe.get_doc("Payment Entry", pe).cancel()
		_sync_funding_fields(req)
		_set_clearance_status(cl, "Settled", docstatus=1)
		with self.assertRaises(ValidationError) as ctx:
			assert_pm_request_cancel_allowed(req)
		self.assertIn("clearance", str(ctx.exception).lower())

	def test_cancel_multi_pe_all_cancelled_allows(self):
		emp = tpm._make_employee()
		tpm._make_holder(emp)
		req = _new_submitted_request(emp, 50_000)
		pe1 = _create_funding_pe(req, 20_000)
		pe2 = _create_funding_pe(req, 30_000)
		_sync_funding_fields(req)
		frappe.get_doc("Payment Entry", pe1).cancel()
		frappe.get_doc("Payment Entry", pe2).cancel()
		_sync_funding_fields(req)
		assert_pm_request_cancel_allowed(req)
		frappe.get_doc("PM Request", req).cancel()
		self.assertEqual(cint(frappe.db.get_value("PM Request", req, "docstatus")), 2)

	def test_cancel_permission_accountant_has_docperm(self):
		meta = frappe.get_meta("PM Request")
		acct = next((p for p in meta.permissions if p.role == "Petty Management Accountant"), None)
		self.assertTrue(acct)
		self.assertTrue(cint(acct.cancel))

	def test_cancel_allowed_with_rejected_clearance_only(self):
		emp = tpm._make_employee()
		tpm._make_holder(emp)
		req = _new_submitted_request(emp, 25_000)
		pe = _create_funding_pe(req, 25_000)
		_sync_funding_fields(req)
		cl = _make_clearance(emp, req, 5_000, submit=True)
		_set_clearance_status(cl, "Rejected")
		frappe.get_doc("Payment Entry", pe).cancel()
		_sync_funding_fields(req)
		assert_pm_request_cancel_allowed(req)
		frappe.get_doc("PM Request", req).cancel()
		self.assertEqual(cint(frappe.db.get_value("PM Request", req, "docstatus")), 2)

	def test_cancel_allowed_with_cancelled_clearance_only(self):
		emp = tpm._make_employee()
		tpm._make_holder(emp)
		req = _new_submitted_request(emp, 25_000)
		pe = _create_funding_pe(req, 25_000)
		_sync_funding_fields(req)
		cl = _make_clearance(emp, req, 5_000, submit=True)
		_force_clearance_cancelled(cl)
		frappe.get_doc("Payment Entry", pe).cancel()
		_sync_funding_fields(req)
		assert_pm_request_cancel_allowed(req)
		frappe.get_doc("PM Request", req).cancel()
		self.assertEqual(cint(frappe.db.get_value("PM Request", req, "docstatus")), 2)

	def test_cancel_permission_user_lacks_docperm(self):
		meta = frappe.get_meta("PM Request")
		user_perm = next((p for p in meta.permissions if p.role == "Petty Management User"), None)
		self.assertTrue(user_perm)
		self.assertFalse(cint(user_perm.cancel))

	def test_cancel_not_pointer_authoritative(self):
		"""Clear pointer while submitted PE remains → still blocked via funding sum."""
		from erpnext_extensions.petty_management.services.funding_queries import sum_submitted_pe_amount

		emp = tpm._make_employee()
		tpm._make_holder(emp)
		req = _new_submitted_request(emp, 10_000)
		pe = _create_funding_pe(req, 10_000)
		_sync_funding_fields(req)
		frappe.db.set_value("PM Request", req, "payment_entry", None, update_modified=False)
		self.assertTrue(frappe.db.exists("Payment Entry", pe))
		self.assertGreater(flt(sum_submitted_pe_amount(req)), 0)
		blockers = get_pm_request_cancel_blockers(req)
		self.assertTrue(any("submitted" in b.lower() for b in blockers))


class TestPmRequestDeleteEligibility(unittest.TestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		_require_site_ready(self)

	def _cancelled_clean_request(self) -> str:
		emp = tpm._make_employee()
		tpm._make_holder(emp)
		req = _new_submitted_request(emp, 8_000)
		frappe.get_doc("PM Request", req).cancel()
		frappe.db.commit()
		return req

	def test_delete_clean_cancelled(self):
		req = self._cancelled_clean_request()
		assert_pm_request_delete_allowed(req)
		frappe.delete_doc("PM Request", req, force=0)
		self.assertFalse(frappe.db.exists("PM Request", req))

	def test_delete_blocked_cancelled_with_cancelled_pe(self):
		emp = tpm._make_employee()
		tpm._make_holder(emp)
		req = _new_submitted_request(emp, 9_000)
		pe = _create_funding_pe(req, 9_000)
		frappe.get_doc("Payment Entry", pe).cancel()
		_sync_funding_fields(req)
		frappe.get_doc("PM Request", req).cancel()
		with self.assertRaises(ValidationError) as ctx:
			assert_pm_request_delete_allowed(req)
		self.assertIn("payment entry", str(ctx.exception).lower())

	def test_delete_blocked_cancelled_with_submitted_pe(self):
		emp = tpm._make_employee()
		tpm._make_holder(emp)
		req = _new_submitted_request(emp, 9_500)
		_create_funding_pe(req, 9_500)
		_sync_funding_fields(req)
		# Cannot cancel Request while funded — delete also blocked while submitted
		with self.assertRaises(ValidationError) as ctx:
			assert_pm_request_delete_allowed(req)
		self.assertIn("submitted", str(ctx.exception).lower())

	def test_delete_blocked_cancelled_with_draft_pe(self):
		emp = tpm._make_employee()
		tpm._make_holder(emp)
		req = _new_submitted_request(emp, 8_500)
		try:
			_draft_pe(req, 1_000)
		except Exception:
			self.skipTest("Could not create draft PE (auto-submit?)")
		# Simulate cancelled Request that still has a draft PE linked (history).
		frappe.db.set_value("PM Request", req, {"docstatus": 2, "status": "Cancelled"}, update_modified=False)
		frappe.db.commit()
		with self.assertRaises(ValidationError) as ctx:
			assert_pm_request_delete_allowed(req)
		self.assertIn("payment entry", str(ctx.exception).lower())

	def test_delete_blocked_cancelled_with_clearance(self):
		emp = tpm._make_employee()
		tpm._make_holder(emp)
		req = _new_submitted_request(emp, 11_000)
		pe = _create_funding_pe(req, 11_000)
		_sync_funding_fields(req)
		cl = _make_clearance(emp, req, 3_000, submit=False)
		_set_clearance_status(cl, "Rejected")  # allow Request cancel
		frappe.get_doc("Payment Entry", pe).cancel()
		_sync_funding_fields(req)
		frappe.get_doc("PM Request", req).cancel()
		with self.assertRaises(ValidationError) as ctx:
			assert_pm_request_delete_allowed(req)
		self.assertIn("clearance", str(ctx.exception).lower())

	def test_delete_blocked_cancelled_with_cancelled_clearance(self):
		emp = tpm._make_employee()
		tpm._make_holder(emp)
		req = _new_submitted_request(emp, 11_000)
		pe = _create_funding_pe(req, 11_000)
		_sync_funding_fields(req)
		cl = _make_clearance(emp, req, 3_000, submit=True)
		_force_clearance_cancelled(cl)
		frappe.get_doc("Payment Entry", pe).cancel()
		_sync_funding_fields(req)
		frappe.get_doc("PM Request", req).cancel()
		with self.assertRaises(ValidationError) as ctx:
			assert_pm_request_delete_allowed(req)
		self.assertIn("clearance", str(ctx.exception).lower())

	def test_delete_blocked_submitted(self):
		emp = tpm._make_employee()
		tpm._make_holder(emp)
		req = _new_submitted_request(emp, 5_000)
		with self.assertRaises(ValidationError) as ctx:
			assert_pm_request_delete_allowed(req)
		self.assertIn("submitted", str(ctx.exception).lower())

	def test_delete_clean_draft(self):
		tpm._ensure_petty_account()
		emp = tpm._make_employee()
		tpm._make_holder(emp)
		req = frappe.new_doc("PM Request")
		req.company = tpm.COMPANY
		req.employee = emp
		req.transaction_date = today()
		req.append("details", {"advance_amount": 1_000})
		req.insert()
		name = req.name
		assert_pm_request_delete_allowed(name)
		frappe.delete_doc("PM Request", name)
		self.assertFalse(frappe.db.exists("PM Request", name))

	def test_delete_draft_blocked_with_clearance(self):
		"""Mistaken draft cleanup blocked when a Clearance allocation row points at the draft."""
		tpm._ensure_petty_account()
		emp = tpm._make_employee()
		tpm._make_holder(emp)
		draft = frappe.new_doc("PM Request")
		draft.company = tpm.COMPANY
		draft.employee = emp
		draft.transaction_date = today()
		draft.append("details", {"advance_amount": 2_000})
		draft.insert()
		# Funded sibling so Clearance can be created, then retarget allocation at draft via DB.
		sib = _new_submitted_request(emp, 20_000)
		pe = _create_funding_pe(sib, 20_000)
		_sync_funding_fields(sib)
		cl = _make_clearance(emp, sib, 2_000, submit=False)
		frappe.db.set_value(
			"PM Clearance Request Allocation",
			{"parent": cl, "pm_request": sib},
			"pm_request",
			draft.name,
			update_modified=False,
		)
		frappe.db.commit()
		with self.assertRaises(ValidationError) as ctx:
			assert_pm_request_delete_allowed(draft.name)
		self.assertIn("clearance", str(ctx.exception).lower())
		# cleanup sibling funding so site stays tidy
		frappe.get_doc("Payment Entry", pe).cancel()

	def test_delete_draft_blocked_with_pe(self):
		"""Draft Request with any linked PE must not be deleted."""
		from erpnext_extensions.petty_management.services.funding_queries import (
			list_payment_entries_for_pm_request,
		)

		tpm._ensure_petty_account()
		emp = tpm._make_employee()
		tpm._make_holder(emp)
		# Use submitted funded request, then force Request back to draft after PE exists —
		# simulates historical PE linked to a draft-looking doc for delete policy.
		req = _new_submitted_request(emp, 6_000)
		pe = _create_funding_pe(req, 6_000)
		frappe.db.set_value("PM Request", req, "docstatus", 0, update_modified=False)
		frappe.db.commit()
		self.assertTrue(list_payment_entries_for_pm_request(req))
		with self.assertRaises(ValidationError) as ctx:
			assert_pm_request_delete_allowed(req)
		self.assertIn("payment entry", str(ctx.exception).lower())
		self.assertTrue(frappe.db.exists("Payment Entry", pe))

	def test_delete_permission_accountant_lacks_docperm(self):
		meta = frappe.get_meta("PM Request")
		acct = next((p for p in meta.permissions if p.role == "Petty Management Accountant"), None)
		self.assertTrue(acct)
		self.assertFalse(cint(acct.delete))
		self.assertTrue(cint(acct.cancel))


if __name__ == "__main__":
	unittest.main()
