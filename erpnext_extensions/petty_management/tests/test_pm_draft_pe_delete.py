# Copyright (c) 2026, Farbod Siyahpoosh and contributors
"""Draft Payment Entry delete policy vs submitted cancel."""

from __future__ import annotations

import unittest

import frappe
from frappe.utils import flt

from unittest.mock import patch

from erpnext_extensions.petty_management.services.allocation_service import (
	get_pm_request_paid_amount,
)
from erpnext_extensions.petty_management.services.request_action_policy import (
	compute_pm_request_action_flags,
)
from erpnext_extensions.petty_management.services.request_service import create_payment_entry
from erpnext_extensions.petty_management.tests.test_pm_request_multi_pe import (
	_create_funding_pe,
	_ensure_pm_settings_bank,
	_new_submitted_request,
	_sync_funding_fields,
)
from erpnext_extensions.petty_management.tests import test_pm_clearance as tpm


class TestPMDraftPaymentEntryDelete(unittest.TestCase):
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

	def _approved_request(self, requested: float) -> str:
		emp = tpm._make_employee()
		self._track("Employee", emp)
		tpm._make_holder(emp)
		req = _new_submitted_request(emp, requested)
		self._track("PM Request", req)
		return req

	def test_draft_pe_delete_without_force(self):
		req = self._approved_request(100_000)
		draft = create_payment_entry(req, paid_amount=20_000)
		self._track("Payment Entry", draft)
		frappe.db.set_value("PM Request", req, "payment_entry", draft, update_modified=False)
		frappe.db.commit()
		frappe.delete_doc("Payment Entry", draft)
		self.assertFalse(frappe.db.exists("Payment Entry", draft))
		_sync_funding_fields(req)
		doc = frappe.get_doc("PM Request", req)
		self.assertEqual(flt(doc.total_draft_pe_amount), 0)
		flags = compute_pm_request_action_flags(doc)
		self.assertTrue(flags["can_create_payment_entry"], msg=flags.get("create_block_reason"))
		self.assertTrue(flags["can_close_pm_request"])

	def test_integration_delete_draft_then_submit_partial(self):
		req = self._approved_request(100_000)
		draft = create_payment_entry(req, paid_amount=20_000)
		self._track("Payment Entry", draft)
		frappe.delete_doc("Payment Entry", draft)
		pe = _create_funding_pe(req, 50_000)
		self._track("Payment Entry", pe)
		_sync_funding_fields(req)
		doc = frappe.get_doc("PM Request", req)
		self.assertEqual(flt(doc.total_paid_amount), 50_000)
		self.assertAlmostEqual(flt(doc.remaining_to_pay), 50_000, places=2)
		self.assertEqual(flt(doc.total_draft_pe_amount), 0)

	def test_submitted_pe_cancel_blocked_when_allocations_exceed_paid_after(self):
		req = self._approved_request(100_000)
		pe = _create_funding_pe(req, 30_000)
		self._track("Payment Entry", pe)
		_sync_funding_fields(req)
		pe_doc = frappe.get_doc("Payment Entry", pe)
		import erpnext_extensions.petty_management.payment_entry_hooks as peh

		with patch.object(peh, "sum_prior_pm_request_allocations", return_value=25_000):
			with self.assertRaises(frappe.ValidationError):
				peh.on_payment_entry_before_cancel(pe_doc)

	def test_submitted_pe_cancel_allowed_without_allocation_conflict(self):
		req = self._approved_request(100_000)
		pe = _create_funding_pe(req, 50_000)
		self._track("Payment Entry", pe)
		_sync_funding_fields(req)
		pe_doc = frappe.get_doc("Payment Entry", pe)
		pe_doc.cancel()
		_sync_funding_fields(req)
		doc = frappe.get_doc("PM Request", req)
		self.assertEqual(flt(get_pm_request_paid_amount(req)), 0)
		self.assertEqual(flt(doc.total_paid_amount), 0)
