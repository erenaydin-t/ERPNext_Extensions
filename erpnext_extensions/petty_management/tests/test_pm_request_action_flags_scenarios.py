# Copyright (c) 2026, Farbod Siyahpoosh and contributors
"""PM Request action flags — multi-PE create/close scenarios (A–E)."""

from __future__ import annotations

import unittest

import frappe
from frappe.utils import flt

from erpnext_extensions.petty_management.services.request_action_policy import (
	MSG_CLOSE_DRAFT_PE,
	compute_pm_request_action_flags,
)
from erpnext_extensions.petty_management.tests.test_pm_request_multi_pe import (
	_approve_pm_request,
	_create_funding_pe,
	_ensure_pm_settings_bank,
	_new_submitted_request,
	_sync_funding_fields,
)
from erpnext_extensions.petty_management.tests import test_pm_clearance as tpm


def _flags(req_name: str) -> dict:
	doc = frappe.get_doc("PM Request", req_name)
	return compute_pm_request_action_flags(doc)


class TestPMRequestActionFlagScenarios(unittest.TestCase):
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

	def _employee_request(self, requested: float) -> str:
		emp = tpm._make_employee()
		self._track("Employee", emp)
		tpm._make_holder(emp)
		req = _new_submitted_request(emp, requested)
		self._track("PM Request", req)
		return req

	def test_scenario_a_partial_submitted_create_visible(self):
		req = self._employee_request(1_000_000)
		pe = _create_funding_pe(req, 200_000)
		self._track("Payment Entry", pe)
		_sync_funding_fields(req)
		f = _flags(req)
		self.assertTrue(f["can_create_payment_entry"], msg=f.get("create_block_reason"))
		self.assertAlmostEqual(flt(f["remaining_to_pay"]), 800_000, places=2)

	def test_scenario_b_remaining_one_create_visible(self):
		req = self._employee_request(1_000_000)
		pe = _create_funding_pe(req, 999_999)
		self._track("Payment Entry", pe)
		_sync_funding_fields(req)
		f = _flags(req)
		self.assertTrue(f["can_create_payment_entry"], msg=f.get("create_block_reason"))
		self.assertGreater(flt(f["remaining_to_pay"]), 0)

	def test_scenario_c_fully_funded_create_hidden(self):
		req = self._employee_request(1_000_000)
		pe = _create_funding_pe(req, 1_000_000)
		self._track("Payment Entry", pe)
		_sync_funding_fields(req)
		f = _flags(req)
		self.assertFalse(f["can_create_payment_entry"])
		self.assertLessEqual(flt(f["remaining_to_pay"]), 1e-6)

	def test_scenario_d_draft_blocks_create_and_close(self):
		from erpnext_extensions.petty_management.services.request_service import create_payment_entry

		req = self._employee_request(1_000_000)
		draft = create_payment_entry(req, paid_amount=20_000)
		self._track("Payment Entry", draft)
		frappe.db.commit()
		f = _flags(req)
		self.assertFalse(f["can_create_payment_entry"])
		self.assertFalse(f["can_close_pm_request"])
		self.assertIn("draft", (f.get("create_block_reason") or "").lower())
		self.assertIn(str(MSG_CLOSE_DRAFT_PE).lower(), (f.get("close_block_reason") or "").lower())

	def test_scenario_e_draft_cancelled_create_visible_again(self):
		from erpnext_extensions.petty_management.services.request_service import create_payment_entry

		req = self._employee_request(1_000_000)
		draft = create_payment_entry(req, paid_amount=20_000)
		self._track("Payment Entry", draft)
		pe = frappe.get_doc("Payment Entry", draft)
		if pe.docstatus == 0:
			frappe.delete_doc("Payment Entry", draft, force=0)
		else:
			pe.cancel()
		_sync_funding_fields(req)
		frappe.db.commit()
		f = _flags(req)
		self.assertTrue(f["can_create_payment_entry"], msg=f.get("create_block_reason"))
		self.assertGreater(flt(f["remaining_to_pay"]), 0)


if __name__ == "__main__":
	unittest.main()
