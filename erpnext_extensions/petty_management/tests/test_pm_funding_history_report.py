# Copyright (c) 2026, Farbod Siyahpoosh and contributors
"""PM Funding History report permission and aggregate consistency."""

from __future__ import annotations

import unittest

import frappe
from frappe.utils import flt

from erpnext_extensions.petty_management.report.pm_funding_history import pm_funding_history
from erpnext_extensions.petty_management.services.funding_queries import (
	list_payment_entries_for_pm_request,
	sum_submitted_pe_amount,
)
from erpnext_extensions.petty_management.tests import test_pm_clearance as tpm
from erpnext_extensions.petty_management.tests.pm_request_security_fixtures import (
	delete_user_if_exists,
	petty_management_user_with_company_only,
)
from erpnext_extensions.petty_management.tests.test_pm_request_multi_pe import (
	_create_funding_pe,
	_new_submitted_request,
	_require_site_ready,
	_sync_funding_fields,
)


class TestPmFundingHistoryReport(unittest.TestCase):
	def setUp(self):
		_require_site_ready(self)
		frappe.set_user("Administrator")
		self._users: list[str] = []
		self._cleanup: list[tuple[str, str]] = []

	def tearDown(self):
		frappe.set_user("Administrator")
		for email in self._users:
			delete_user_if_exists(email)
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

	def test_cross_company_user_does_not_see_other_company_rows(self):
		other = "PM CrossCo Test B"
		if not frappe.db.exists("Company", other):
			base = frappe.get_doc("Company", tpm.COMPANY)
			c = frappe.new_doc("Company")
			c.company_name = other
			c.abbr = "PMXB"
			c.default_currency = base.default_currency
			c.country = base.country or "Iran"
			c.insert(ignore_permissions=True)
			frappe.db.commit()

		emp = tpm._make_employee()
		self._track("Employee", emp)
		tpm._make_holder(emp)
		req_a = _new_submitted_request(emp, 10_000.0)
		self._track("PM Request", req_a)
		_create_funding_pe(req_a, 10_000.0)
		_sync_funding_fields(req_a)

		email = petty_management_user_with_company_only(other, tag="rep_co")
		self._users.append(email)
		frappe.set_user(email)
		_columns, data = pm_funding_history.execute({})
		names = {row.get("pm_request") for row in data if row.get("indent", 0) == 0}
		self.assertNotIn(req_a, names)

	def test_report_lists_all_payment_entries_for_request(self):
		emp = tpm._make_employee()
		self._track("Employee", emp)
		tpm._make_holder(emp)
		req = _new_submitted_request(emp, 80_000.0)
		self._track("PM Request", req)
		_create_funding_pe(req, 25_000.0)
		_create_funding_pe(req, 15_000.0)
		_sync_funding_fields(req)

		_columns, data = pm_funding_history.execute({"company": tpm.COMPANY})
		summary = next((r for r in data if r.get("pm_request") == req and r.get("indent", 0) == 0), None)
		self.assertIsNotNone(summary)
		pe_rows = [r for r in data if r.get("pm_request") == req and r.get("indent", 0) == 1]
		linked = list_payment_entries_for_pm_request(req)
		self.assertEqual(len(pe_rows), len(linked))
		self.assertGreaterEqual(len(pe_rows), 2)

	def test_report_summary_paid_matches_funding_queries(self):
		emp = tpm._make_employee()
		self._track("Employee", emp)
		tpm._make_holder(emp)
		req = _new_submitted_request(emp, 50_000.0)
		self._track("PM Request", req)
		_create_funding_pe(req, 20_000.0)
		_sync_funding_fields(req)

		_columns, data = pm_funding_history.execute({"company": tpm.COMPANY})
		summary = next((r for r in data if r.get("pm_request") == req and r.get("indent", 0) == 0), None)
		self.assertIsNotNone(summary)
		self.assertAlmostEqual(flt(summary["paid"]), flt(sum_submitted_pe_amount(req)), places=2)


if __name__ == "__main__":
	unittest.main()
