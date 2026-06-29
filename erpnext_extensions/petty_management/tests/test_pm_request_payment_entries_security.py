# Copyright (c) 2026, Farbod Siyahpoosh and contributors
"""Security and robustness tests for get_pm_request_payment_entries API."""

from __future__ import annotations

import unittest

import frappe
from frappe.exceptions import DoesNotExistError, ValidationError

from erpnext_extensions.petty_management.doctype.pm_request.pm_request import (
	get_pm_request_payment_entries,
)
from erpnext_extensions.petty_management.services.request_api_guard import get_pm_request_doc_for_read
from erpnext_extensions.petty_management.tests import test_pm_clearance as tpm
from erpnext_extensions.petty_management.tests.pm_request_security_fixtures import (
	delete_user_if_exists,
	non_pm_user_for_read_denial,
	petty_management_user_with_company_only,
)
from erpnext_extensions.petty_management.tests.test_pm_request_multi_pe import (
	_create_funding_pe,
	_ensure_pm_settings_bank,
	_new_submitted_request,
	_require_site_ready,
)


def _ensure_isolation_test_companies() -> tuple[str, str]:
	tpm._ensure_company_context()
	company_a = tpm.COMPANY or frappe.get_all("Company", pluck="name", limit=1)[0]
	company_b = "PM CrossCo Test B"
	if not frappe.db.exists("Company", company_b):
		base = frappe.get_doc("Company", company_a)
		c = frappe.new_doc("Company")
		c.company_name = company_b
		c.abbr = "PMXB"
		c.default_currency = base.default_currency
		c.country = base.country or "Iran"
		c.insert(ignore_permissions=True)
		frappe.db.commit()
	return company_a, company_b


def _payment_entries_rows(payload) -> list:
	if isinstance(payload, dict):
		return payload.get("payment_entries") or []
	if isinstance(payload, list):
		return payload
	return []


class TestPmRequestPaymentEntriesSecurity(unittest.TestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		_require_site_ready(self)
		_ensure_pm_settings_bank()

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_empty_pm_request_raises_validation_error(self):
		with self.assertRaises(ValidationError):
			get_pm_request_payment_entries("")
		with self.assertRaises(ValidationError):
			get_pm_request_payment_entries("   ")

	def test_missing_pm_request_raises_does_not_exist(self):
		with self.assertRaises(DoesNotExistError):
			get_pm_request_payment_entries("REQ-DOES-NOT-EXIST-00000")

	def test_guest_raises_permission_error_not_type_error(self):
		emp = tpm._make_employee()
		tpm._make_holder(emp)
		req = _new_submitted_request(emp, 5_000)
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			get_pm_request_payment_entries(req)

	def test_unauthorized_user_raises_permission_error(self):
		emp = tpm._make_employee()
		tpm._make_holder(emp)
		req = _new_submitted_request(emp, 6_000)
		test_user = non_pm_user_for_read_denial(tag="unauth_pe")
		try:
			frappe.set_user(test_user)
			with self.assertRaises(frappe.PermissionError):
				get_pm_request_payment_entries(req)
		finally:
			frappe.set_user("Administrator")
			delete_user_if_exists(test_user)

	def test_cross_company_user_permission_blocked(self):
		from erpnext_extensions.petty_management.services.request_api_guard import (
			assert_pm_request_company_user_permission,
		)

		company_a, company_b = _ensure_isolation_test_companies()
		tpm._ensure_company_context()
		orig_company = tpm.COMPANY
		try:
			tpm.COMPANY = company_a
			emp = tpm._make_employee()
			tpm._make_holder(emp)
			req = _new_submitted_request(emp, 6_000)
		finally:
			tpm.COMPANY = orig_company

		doc = get_pm_request_doc_for_read(req)
		test_user = petty_management_user_with_company_only(company_b, tag="crossco")
		try:
			frappe.set_user(test_user)
			with self.assertRaises(frappe.PermissionError):
				assert_pm_request_company_user_permission(doc)
			with self.assertRaises(frappe.PermissionError):
				get_pm_request_payment_entries(req)
		finally:
			frappe.set_user("Administrator")
			delete_user_if_exists(test_user)

	def test_admin_lists_draft_and_submitted_statuses(self):
		from erpnext_extensions.petty_management.services.request_service import create_payment_entry

		emp = tpm._make_employee()
		tpm._make_holder(emp)
		req = _new_submitted_request(emp, 40_000)
		settings = frappe.get_single("PM Settings")
		auto = settings.auto_submit_payment_entry
		settings.auto_submit_payment_entry = 0
		settings.save(ignore_permissions=True)
		frappe.db.commit()
		try:
			draft_name = create_payment_entry(req, paid_amount=5_000)
			payload = get_pm_request_payment_entries(req)
			statuses = {r["payment_entry"]: r["status"] for r in _payment_entries_rows(payload)}
			self.assertEqual(statuses.get(draft_name), "Draft")
			pe = frappe.get_doc("Payment Entry", draft_name)
			pe.submit()
			frappe.db.commit()
			payload2 = get_pm_request_payment_entries(req)
			statuses2 = {r["payment_entry"]: r["status"] for r in _payment_entries_rows(payload2)}
			self.assertEqual(statuses2.get(draft_name), "Submitted")
		finally:
			settings.auto_submit_payment_entry = auto
			settings.save(ignore_permissions=True)
			frappe.db.commit()

	def test_response_version_id_monotonic_on_notify(self):
		from erpnext_extensions.petty_management.services.request_api_guard import (
			bump_pm_request_response_version,
			get_pm_request_response_version,
			notify_pm_request_funding_updated,
		)

		emp = tpm._make_employee()
		tpm._make_holder(emp)
		req = _new_submitted_request(emp, 5_000)
		v0 = get_pm_request_response_version(req)
		v1 = notify_pm_request_funding_updated(req, "on_payment_entry_created")
		v2 = bump_pm_request_response_version(req)
		self.assertGreater(int(v1), int(v0))
		self.assertGreater(int(v2), int(v1))
		payload = get_pm_request_payment_entries(req)
		self.assertEqual(str(payload.get("response_version_id")), v2)

	def test_get_pm_request_doc_for_read_enforces_check_permission(self):
		emp = tpm._make_employee()
		tpm._make_holder(emp)
		req = _new_submitted_request(emp, 4_000)
		doc = get_pm_request_doc_for_read(req)
		self.assertEqual(doc.name, req)
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			get_pm_request_doc_for_read(req)


if __name__ == "__main__":
	unittest.main()
