# Copyright (c) 2026, Farbod Siyahpoosh and contributors
"""PM Request allocation security: holder, company, closed request, aggregate paid."""

from __future__ import annotations

import unittest

import frappe
from frappe.utils import cint, flt

from erpnext_extensions.petty_management.services import allocation_service
from erpnext_extensions.petty_management.services.funding_queries import sum_submitted_pe_amount
from erpnext_extensions.petty_management.tests import test_pm_clearance as tpm
from erpnext_extensions.petty_management.tests.test_pm_request_multi_pe import (
	_close_pm_request,
	_create_funding_pe,
	_new_submitted_request,
	_require_site_ready,
	_sync_funding_fields,
)


class TestPmRequestAllocationSecurity(unittest.TestCase):
	def setUp(self):
		_require_site_ready(self)
		frappe.set_user("Administrator")
		self._cleanup: list[tuple[str, str]] = []

	def tearDown(self):
		frappe.set_user("Administrator")
		for doctype, name in reversed(self._cleanup):
			try:
				if frappe.db.exists(doctype, name):
					doc = frappe.get_doc(doctype, name)
					if getattr(doc, "docstatus", 0) == 1:
						doc.cancel()
					frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
			except Exception:
				pass
		frappe.db.commit()

	def _track(self, doctype: str, name: str) -> None:
		self._cleanup.append((doctype, name))

	def test_allocation_wrong_holder_blocked(self):
		emp_a = tpm._make_employee()
		emp_b = tpm._make_employee()
		self._track("Employee", emp_a)
		self._track("Employee", emp_b)
		tpm._make_holder(emp_a)
		holder_b = tpm._make_holder(emp_b)
		req_name, _pe = tpm._fund_pm_request(emp_a, 20_000.0)
		self._track("PM Request", req_name)

		ok, reason = allocation_service.pm_request_passes_clearance_filters(
			req_name,
			employee=emp_b,
			company=tpm.COMPANY,
			holder=holder_b,
			clearance_petty=tpm._ensure_petty_account(),
		)
		self.assertFalse(ok)
		self.assertTrue(
			"employee" in (reason or "").lower() or "holder" in (reason or "").lower(),
			msg=reason,
		)

	def test_allocation_wrong_company_blocked(self):
		emp = tpm._make_employee()
		self._track("Employee", emp)
		tpm._make_holder(emp)
		req_name, _pe = tpm._fund_pm_request(emp, 15_000.0)
		self._track("PM Request", req_name)
		other_company = "PM CrossCo Test B"
		if not frappe.db.exists("Company", other_company):
			base = frappe.get_doc("Company", tpm.COMPANY)
			c = frappe.new_doc("Company")
			c.company_name = other_company
			c.abbr = "PMXB"
			c.default_currency = base.default_currency
			c.country = base.country or "Iran"
			c.insert(ignore_permissions=True)
			frappe.db.commit()

		ok, reason = allocation_service.pm_request_passes_clearance_filters(
			req_name,
			employee=emp,
			company=other_company,
			holder=frappe.db.get_value("PM Request", req_name, "holder"),
			clearance_petty=tpm._ensure_petty_account(),
		)
		self.assertFalse(ok)
		self.assertIn("company", (reason or "").lower())

	def test_closed_pm_request_allocation_allowed_up_to_available(self):
		emp = tpm._make_employee()
		self._track("Employee", emp)
		tpm._make_holder(emp)
		req = _new_submitted_request(emp, 100_000.0)
		self._track("PM Request", req)
		_create_funding_pe(req, 40_000.0)
		_sync_funding_fields(req)
		_close_pm_request(req, close_reason="Partial Approval")
		_sync_funding_fields(req)

		from erpnext_extensions.petty_management.services.request_api_guard import get_pm_request_doc_internal

		doc = get_pm_request_doc_internal(req)
		self.assertEqual(cint(doc.is_closed), 1)
		available = allocation_service.get_pm_request_available_amount(req)
		self.assertAlmostEqual(available, 40_000.0, places=2)

		holder = doc.holder
		petty = tpm._ensure_petty_account()
		ok, _reason = allocation_service.pm_request_passes_clearance_filters(
			req,
			employee=emp,
			company=tpm.COMPANY,
			holder=holder,
			clearance_petty=petty,
		)
		self.assertTrue(ok)

	def test_allocation_does_not_check_is_closed(self):
		text = frappe.get_app_path("erpnext_extensions") + "/petty_management/services/allocation_service.py"
		with open(text, encoding="utf-8") as f:
			body = f.read()
		self.assertNotIn("is_closed", body)

	def test_allocation_uses_aggregate_submitted_pe_amount(self):
		emp = tpm._make_employee()
		self._track("Employee", emp)
		tpm._make_holder(emp)
		req = _new_submitted_request(emp, 100_000.0)
		self._track("PM Request", req)
		_create_funding_pe(req, 30_000.0)
		_create_funding_pe(req, 20_000.0)
		_sync_funding_fields(req)

		paid = allocation_service.get_pm_request_paid_amount(req)
		self.assertAlmostEqual(paid, flt(sum_submitted_pe_amount(req)), places=2)
		self.assertAlmostEqual(paid, 50_000.0, places=2)
		available = allocation_service.get_pm_request_available_amount(req)
		self.assertAlmostEqual(available, 50_000.0, places=2)


if __name__ == "__main__":
	unittest.main()
