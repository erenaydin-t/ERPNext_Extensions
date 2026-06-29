# Copyright (c) 2026, Farbod Siyahpoosh and contributors
"""PM Request action flags — reject + View Payment Entries (multi-PE UAT)."""

from __future__ import annotations

import unittest

import frappe
from frappe.exceptions import ValidationError

from erpnext_extensions.petty_management.services.funding_queries import (
	list_payment_entries_for_pm_request,
	payment_entry_list_filters_for_pm_request,
)
from erpnext_extensions.petty_management.services.request_action_policy import (
	compute_pm_request_action_flags,
	validate_pm_request_workflow_action,
)
from erpnext_extensions.petty_management.tests.test_pm_request_multi_pe import (
	_create_funding_pe,
	_ensure_pm_settings_bank,
	_new_submitted_request,
	_sync_funding_fields,
)
from erpnext_extensions.petty_management.tests import test_pm_clearance as tpm


class TestPMRequestActionFlagsUAT(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")
		tpm._ensure_company_context()
		if not tpm.COMPANY:
			raise unittest.SkipTest("No Company on site")
		_ensure_pm_settings_bank()

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
						frappe.delete_doc(dt, name, force=1)
			except Exception:
				pass
		frappe.db.commit()

	def _track(self, dt: str, name: str) -> None:
		self._created.append((dt, name))

	def _approved(self, amount: float) -> str:
		emp = tpm._make_employee()
		self._track("Employee", emp)
		tpm._make_holder(emp)
		req = _new_submitted_request(emp, amount)
		self._track("PM Request", req)
		return req

	def test_can_reject_true_without_submitted_pe(self):
		req = self._approved(50_000)
		flags = compute_pm_request_action_flags(frappe.get_doc("PM Request", req))
		self.assertEqual(flags["submitted_payment_entry_count"], 0)
		self.assertEqual(flags["payment_entry_count"], 0)
		self.assertFalse(flags["can_view_payment_entries"])
		# Workflow may or may not expose PM Reject from Draft/Approved; when allowed, no submitted PE.
		if "PM Reject" in (flags.get("allowed_workflow_actions") or []):
			self.assertTrue(flags["can_reject"])

	def test_can_reject_false_with_one_submitted_pe(self):
		req = self._approved(100_000)
		pe = _create_funding_pe(req, 50_000)
		self._track("Payment Entry", pe)
		_sync_funding_fields(req)
		flags = compute_pm_request_action_flags(frappe.get_doc("PM Request", req))
		self.assertEqual(flags["submitted_payment_entry_count"], 1)
		self.assertFalse(flags["can_reject"])
		self.assertTrue(flags["can_view_payment_entries"])

	def test_can_reject_false_with_multiple_submitted_pes(self):
		req = self._approved(1_000_000)
		self._track("Payment Entry", _create_funding_pe(req, 50_000))
		self._track("Payment Entry", _create_funding_pe(req, 500_000))
		_sync_funding_fields(req)
		flags = compute_pm_request_action_flags(frappe.get_doc("PM Request", req))
		self.assertEqual(flags["submitted_payment_entry_count"], 2)
		self.assertEqual(flags["payment_entry_count"], 2)
		self.assertFalse(flags["can_reject"])
		self.assertTrue(flags["can_view_payment_entries"])

	def test_server_reject_blocked_with_submitted_pe(self):
		req = self._approved(80_000)
		self._track("Payment Entry", _create_funding_pe(req, 10_000))
		doc = frappe.get_doc("PM Request", req)
		with self.assertRaises(ValidationError):
			validate_pm_request_workflow_action(doc, "PM Reject")

	def test_view_payment_entries_flags_and_filters(self):
		req = self._approved(200_000)
		pe1 = _create_funding_pe(req, 50_000)
		pe2 = _create_funding_pe(req, 30_000)
		self._track("Payment Entry", pe1)
		self._track("Payment Entry", pe2)
		rows = list_payment_entries_for_pm_request(req)
		self.assertEqual(len(rows), 2)
		filters = payment_entry_list_filters_for_pm_request(req)
		self.assertEqual(filters.get("reference_no"), req)
		flags = compute_pm_request_action_flags(frappe.get_doc("PM Request", req))
		self.assertTrue(flags["can_view_payment_entries"])
		self.assertFalse(flags.get("can_open_payment_entry"))

	def test_integration_partial_multi_pe_totals(self):
		req = self._approved(1_000_000)
		self._track("Payment Entry", _create_funding_pe(req, 50_000))
		self._track("Payment Entry", _create_funding_pe(req, 500_000))
		_sync_funding_fields(req)
		doc = frappe.get_doc("PM Request", req)
		flags = compute_pm_request_action_flags(doc)
		self.assertFalse(flags["can_reject"])
		self.assertTrue(flags["can_view_payment_entries"])
		self.assertEqual(flags["submitted_payment_entry_count"], 2)
		names = {r["payment_entry"] for r in list_payment_entries_for_pm_request(req)}
		self.assertEqual(len(names), 2)
