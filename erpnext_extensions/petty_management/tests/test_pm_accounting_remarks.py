# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

import unittest

import frappe
from frappe.utils import cint, flt, today

from erpnext_extensions.petty_management.tests import test_pm_clearance as tpm


class TestPMAccountingRemarks(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")
		tpm._ensure_company_context()
		if not tpm.COMPANY:
			raise unittest.SkipTest("No Company on site.")
		tpm._ensure_petty_account()

	def setUp(self):
		frappe.set_user("Administrator")

	def tearDown(self):
		frappe.db.rollback()

	def _approved_pm_request(self, *, remark: str = ""):
		emp = tpm._make_employee()
		tpm._make_holder(emp)
		req = frappe.new_doc("PM Request")
		req.company = tpm.COMPANY
		req.employee = emp
		req.transaction_date = today()
		if remark:
			req.remark = remark
		req.append("details", {"advance_amount": 10_000})
		req.insert()
		req.submit()
		tpm._finance_clear_pm_request(req.name)
		req.reload()
		return req

	def test_funding_template_on_payment_entry_with_custom_remarks(self):
		tpm._ensure_company_context()
		if not tpm.BANK_ACCOUNT:
			self.skipTest("No bank account for PM Settings.")

		settings = frappe.get_single("PM Settings")
		old_tpl = settings.get("funding_payment_entry_remark_template")
		settings.funding_payment_entry_remark_template = (
			"پرداخت تنخواه {employee_name}\nدرخواست: {pm_request}\nمبلغ: {total_amount}"
		)
		settings.save(ignore_permissions=True)

		try:
			req = self._approved_pm_request()
			from erpnext_extensions.petty_management.services.request_service import (
				_build_payment_entry,
			)

			pe = _build_payment_entry(req, tpm.BANK_ACCOUNT, flt(req.total_requested_amount))
			self.assertEqual(cint(pe.custom_remarks), 1)
			self.assertIn("پرداخت تنخواه", pe.remarks or "")
			self.assertIn(req.name, pe.remarks or "")

			pe.insert(ignore_permissions=True)
			pe.reload()
			self.assertEqual(cint(pe.custom_remarks), 1)
			self.assertIn("پرداخت تنخواه", pe.remarks or "")
			self.assertNotIn("paid to", (pe.remarks or "").lower())
		finally:
			settings.funding_payment_entry_remark_template = old_tpl
			settings.save(ignore_permissions=True)

	def test_funding_fallback_when_template_empty(self):
		settings = frappe.get_single("PM Settings")
		old_tpl = settings.get("funding_payment_entry_remark_template")
		settings.funding_payment_entry_remark_template = ""
		settings.save(ignore_permissions=True)

		try:
			req = self._approved_pm_request()
			from erpnext_extensions.petty_management.services.request_service import _build_payment_entry

			pe = _build_payment_entry(req, tpm.BANK_ACCOUNT, flt(req.total_requested_amount))
			self.assertIn(req.name, pe.remarks or "")
		finally:
			settings.funding_payment_entry_remark_template = old_tpl
			settings.save(ignore_permissions=True)

	def test_user_remark_appended_on_funding(self):
		settings = frappe.get_single("PM Settings")
		old_tpl = settings.get("funding_payment_entry_remark_template")
		settings.funding_payment_entry_remark_template = "Fund {pm_request}"
		settings.save(ignore_permissions=True)

		try:
			req = self._approved_pm_request(remark="Pay urgent")
			from erpnext_extensions.petty_management.services.request_service import _build_payment_entry

			pe = _build_payment_entry(req, tpm.BANK_ACCOUNT, flt(req.total_requested_amount))
			self.assertIn("User Remark:", pe.remarks or "")
			self.assertIn("Pay urgent", pe.remarks or "")
		finally:
			settings.funding_payment_entry_remark_template = old_tpl
			settings.save(ignore_permissions=True)

	def test_settlement_template_on_journal_entry_user_remark(self):
		tpm._ensure_company_context()
		if not tpm.BANK_ACCOUNT:
			self.skipTest("No bank account.")

		settings = frappe.get_single("PM Settings")
		old_tpl = settings.get("settlement_journal_entry_remark_template")
		settings.settlement_journal_entry_remark_template = "تسویه {pm_clearance} مبلغ {total_amount}"
		settings.save(ignore_permissions=True)

		try:
			emp = tpm._make_employee()
			tpm._make_holder(emp)
			req_name, _pe = tpm._fund_pm_request(emp, 20_000.0)
			pi = tpm._make_pi_outstanding(5_000)
			pi.insert()
			pi.submit()

			cl = frappe.new_doc("PM Clearance")
			cl.company = tpm.COMPANY
			cl.employee = emp
			cl.transaction_date = today()
			tpm._append_pm_clearance_detail_row(
				cl,
				{
					"settlement_type": "Purchase Invoice",
					"purchase_invoice": pi.name,
					"allocated_amount": 5_000,
				},
			)
			cl.append("request_allocations", {"pm_request": req_name, "allocated_amount": 5_000})
			cl.insert()
			cl.submit()
			tpm._approve_pm_clearance_for_reservation(cl.name)

			from erpnext_extensions.petty_management.services.journal_entry_service import (
				create_clearance_journal_entry,
			)

			je = create_clearance_journal_entry(cl)
			je.reload()
			self.assertIn("تسویه", je.user_remark or "")
			self.assertIn(cl.name, je.user_remark or "")
		finally:
			settings.settlement_journal_entry_remark_template = old_tpl
			settings.save(ignore_permissions=True)


if __name__ == "__main__":
	unittest.main()
