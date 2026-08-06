# Copyright (c) 2026, Farbod Siyahpoosh and contributors
"""PM Request action visibility matrix (Create / Reject / View) — v3.8.5 regression."""

from __future__ import annotations

import unittest

import frappe
from frappe.utils import flt
from frappe.utils.password import update_password

from erpnext_extensions.petty_management.services.request_action_policy import (
	MSG_CLOSE_DRAFT_PE,
	compute_pm_request_action_flags,
)
from erpnext_extensions.petty_management.tests import test_pm_clearance as tpm
from erpnext_extensions.petty_management.tests.pm_request_security_fixtures import (
	_append_user_role,
	_insert_user_row,
	delete_user_if_exists,
)
from erpnext_extensions.petty_management.tests.test_pm_request_multi_pe import (
	_create_funding_pe,
	_ensure_pm_settings_bank,
	_new_submitted_request,
	_sync_funding_fields,
)


def _flags(req_name: str) -> dict:
	return compute_pm_request_action_flags(frappe.get_doc("PM Request", req_name))


class TestPMRequestActionVisibility(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")
		tpm._ensure_company_context()
		if not tpm.COMPANY:
			raise unittest.SkipTest("No Company on site")
		_ensure_pm_settings_bank()

	def setUp(self):
		self._created: list[tuple[str, str]] = []
		self._users: list[str] = []

	def tearDown(self):
		frappe.set_user("Administrator")
		for email in self._users:
			delete_user_if_exists(email)
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

	def test_a_fully_funded_submitted_pe_view_only(self):
		"""A) Approved + submitted PE covering full amount: view yes, create/reject no."""
		req = self._approved(100_000)
		pe = _create_funding_pe(req, 100_000)
		self._track("Payment Entry", pe)
		_sync_funding_fields(req)
		f = _flags(req)
		self.assertEqual(f["submitted_payment_entry_count"], 1)
		self.assertLessEqual(flt(f["remaining_to_pay"]), 1e-6)
		self.assertTrue(f["can_view_payment_entries"])
		self.assertFalse(f["can_create_payment_entry"])
		self.assertFalse(f["can_reject"])

	def test_b_approved_no_pe_can_create(self):
		"""B) Approved with no Payment Entry: Create allowed."""
		req = self._approved(75_000)
		f = _flags(req)
		self.assertEqual(f["payment_entry_count"], 0)
		self.assertTrue(f["can_create_payment_entry"], msg=f.get("create_block_reason"))
		self.assertFalse(f["can_view_payment_entries"])

	def test_c_draft_pe_blocks_create_and_close(self):
		"""C) Draft PE: Create and Close blocked per existing rules."""
		from erpnext_extensions.petty_management.services.request_service import create_payment_entry

		req = self._approved(90_000)
		draft = create_payment_entry(req, paid_amount=10_000)
		self._track("Payment Entry", draft)
		frappe.db.commit()
		f = _flags(req)
		self.assertFalse(f["can_create_payment_entry"])
		self.assertFalse(f["can_close_pm_request"])
		self.assertIn("draft", (f.get("create_block_reason") or "").lower())
		self.assertIn(str(MSG_CLOSE_DRAFT_PE).lower(), (f.get("close_block_reason") or "").lower())

	def test_d_accounts_and_petty_roles_can_view_flags(self):
		"""D) Accounts User + Petty Management roles can read view-payment flags."""
		req = self._approved(120_000)
		pe = _create_funding_pe(req, 120_000)
		self._track("Payment Entry", pe)
		_sync_funding_fields(req)

		email = f"pm_vis_{frappe.generate_hash(length=10)}@example.com"
		_insert_user_row(email, "PM", "Visibility")
		self._users.append(email)
		for role in (
			"Accounts User",
			"Petty Management User",
			"Petty Management Manager",
			"Petty Management Accountant",
			"Petty Management Admin",
			"Petty Management Auditor",
		):
			_append_user_role(email, role)
		update_password(email, "pm_sec_test_1")
		frappe.db.commit()

		frappe.set_user(email)
		from erpnext_extensions.petty_management.doctype.pm_request.pm_request import (
			get_pm_request_action_flags,
		)

		api_flags = get_pm_request_action_flags(req)
		self.assertTrue(api_flags["can_view_payment_entries"])
		self.assertFalse(api_flags["can_create_payment_entry"])
		self.assertFalse(api_flags["can_reject"])
		self.assertTrue(frappe.has_permission("PM Request", "read", doc=req))
		self.assertTrue(frappe.has_permission("Payment Entry", "read"))


if __name__ == "__main__":
	unittest.main()
