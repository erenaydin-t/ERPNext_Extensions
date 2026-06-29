"""Desk UI smoke fixtures for PM Request intro / actions."""

from __future__ import annotations

import frappe

from erpnext_extensions.petty_management.tests import test_pm_clearance as tpm
from erpnext_extensions.petty_management.tests.test_pm_request_multi_pe import (
	_ensure_pm_settings_bank,
)


@frappe.whitelist()
def get_draft_pm_request() -> dict:
	tpm._ensure_company_context()
	if not tpm.COMPANY:
		frappe.throw("No Company on site")
	_ensure_pm_settings_bank()
	emp = tpm._make_employee()
	tpm._make_holder(emp)
	doc = frappe.get_doc(
		{
			"doctype": "PM Request",
			"employee": emp,
			"company": tpm.COMPANY,
			"transaction_date": frappe.utils.today(),
			"details": [{"advance_amount": 25_000}],
		}
	)
	doc.insert()
	frappe.db.commit()
	return {"pm_request": doc.name}
