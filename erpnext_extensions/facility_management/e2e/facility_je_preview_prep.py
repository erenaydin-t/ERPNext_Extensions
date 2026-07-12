"""Prep facilities/repayments for JE preview browser E2E."""

from __future__ import annotations

import frappe
from frappe.utils import random_string, today

from erpnext_extensions.facility_management.facility_accounting import preview_receipt_journal_entry
from erpnext_extensions.facility_management.facility_e2e_context import (
	apply_facility_test_accounts,
	ensure_bank_master,
)
from erpnext_extensions.facility_management.facility_settings_doc import get_facility_settings_doc


def prepare_receipt_preview_facility():
	frappe.set_user("Administrator")
	company = frappe.db.get_value("Company", {}, "name", order_by="creation asc")
	bank = frappe.db.get_value("Bank", {}, "name", order_by="creation asc") or ensure_bank_master()
	fac = frappe.new_doc("Facility")
	fac.facility_name = f"E2E Receipt Preview {random_string(4)}"
	fac.company = company
	fac.bank = bank
	fac.contract_date = today()
	fac.receive_date = today()
	fac.principal_amount = 8000
	fac.profit_amount = 1000
	apply_facility_test_accounts(fac)
	fac.insert(ignore_permissions=True)
	frappe.db.commit()
	prev = preview_receipt_journal_entry(fac)
	return {
		"facility": fac.name,
		"preview": prev,
		"je_count": frappe.db.count("Journal Entry"),
	}


def prepare_repayment_preview_draft():
	from erpnext_extensions.facility_management.e2e.facility_repayment_je_prep import (
		create_draft_repayment_for_e2e,
	)

	out = create_draft_repayment_for_e2e()
	out["je_count"] = frappe.db.count("Journal Entry")
	return out


def prepare_facility_missing_bank_account():
	frappe.set_user("Administrator")
	company = frappe.db.get_value("Company", {}, "name", order_by="creation asc")
	settings = get_facility_settings_doc(company)
	bank = frappe.db.get_value("Bank", {}, "name", order_by="creation asc")
	fac = frappe.new_doc("Facility")
	fac.facility_name = f"E2E Preview Fail {random_string(4)}"
	fac.company = company
	fac.bank = bank
	fac.contract_date = today()
	fac.receive_date = today()
	fac.principal_amount = 5000
	fac.profit_amount = 0
	fac.is_opening_facility = 1
	if settings and settings.get("default_loan_payable_account"):
		fac.loan_payable_account = settings.get("default_loan_payable_account")
	fac.insert(ignore_permissions=True)
	frappe.db.commit()
	return {"facility": fac.name}
