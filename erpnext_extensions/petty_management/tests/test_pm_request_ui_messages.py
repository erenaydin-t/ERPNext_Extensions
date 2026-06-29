# Copyright (c) 2026, Farbod Siyahpoosh and contributors
"""PM Request Desk UI messages and View Payment Entries flags."""

from __future__ import annotations

import unittest

import frappe
from frappe.utils import cint

from erpnext_extensions.petty_management.services.request_action_policy import (
	MSG_CLOSED_FROZEN,
	MSG_SUBMIT_FIRST,
	build_pm_request_ui_messages,
	compute_pm_request_action_flags,
)
from erpnext_extensions.petty_management.tests import test_pm_clearance as tpm
from erpnext_extensions.petty_management.tests.test_pm_request_multi_pe import (
	_create_funding_pe,
	_ensure_pm_settings_bank,
	_new_submitted_request,
	_sync_funding_fields,
)


class TestPMRequestUIMessages(unittest.TestCase):
	def test_build_ui_messages_draft_single_submit(self):
		doc = frappe._dict({"docstatus": 0, "is_closed": 0, "name": "REQ-TEST"})
		msgs = build_pm_request_ui_messages(
			doc,
			can_create=False,
			create_block_reason=str(MSG_SUBMIT_FIRST),
			can_close=False,
			close_block_reason=str(MSG_SUBMIT_FIRST),
			can_reject_wf=False,
			reject_block_reason="",
		)
		self.assertEqual(len(msgs), 1)
		self.assertEqual(msgs[0], str(MSG_SUBMIT_FIRST))

	def test_build_ui_messages_closed_single(self):
		doc = frappe._dict({"docstatus": 1, "is_closed": 1, "name": "REQ-TEST"})
		msgs = build_pm_request_ui_messages(
			doc,
			can_create=False,
			create_block_reason="",
			can_close=False,
			close_block_reason="Already closed.",
			can_reject_wf=False,
			reject_block_reason="",
		)
		self.assertEqual(msgs, [str(MSG_CLOSED_FROZEN)])


class TestPMRequestViewPaymentEntriesFlags(unittest.TestCase):
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

	def test_compute_flags_ui_messages_unique_draft(self):
		emp = tpm._make_employee()
		self._track("Employee", emp)
		tpm._make_holder(emp)
		doc = frappe.get_doc(
			{
				"doctype": "PM Request",
				"employee": emp,
				"company": tpm.COMPANY,
				"transaction_date": frappe.utils.today(),
				"details": [{"advance_amount": 10_000}],
			}
		)
		doc.insert()
		self._track("PM Request", doc.name)
		flags = compute_pm_request_action_flags(doc)
		msgs = flags.get("ui_messages") or []
		self.assertEqual(len(msgs), len(set(msgs)))
		self.assertEqual(len(msgs), 1)
		self.assertIn("Submit", msgs[0])

	def test_view_payment_entries_open_not_closed_with_pe(self):
		req = self._approved(100_000)
		pe = _create_funding_pe(req, 25_000)
		self._track("Payment Entry", pe)
		_sync_funding_fields(req)
		doc = frappe.get_doc("PM Request", req)
		flags = compute_pm_request_action_flags(doc)
		self.assertFalse(cint(doc.is_closed))
		self.assertGreater(flags["payment_entry_count"], 0)
		self.assertTrue(flags["can_view_payment_entries"])

	def test_view_payment_entries_when_closed(self):
		req = self._approved(100_000)
		pe = _create_funding_pe(req, 25_000)
		self._track("Payment Entry", pe)
		_sync_funding_fields(req)
		frappe.db.set_value("PM Request", req, "is_closed", 1)
		doc = frappe.get_doc("PM Request", req)
		flags = compute_pm_request_action_flags(doc)
		self.assertTrue(flags["can_view_payment_entries"])
		self.assertTrue(cint(flags["is_closed"]))

