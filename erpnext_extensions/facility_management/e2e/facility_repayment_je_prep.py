"""Prep active Facility for repayment JE E2E."""

from __future__ import annotations

import frappe
from frappe.utils import random_string, today

from erpnext_extensions.facility_management.doctype.facility.facility import create_receipt_journal_entry
from erpnext_extensions.facility_management.facility_accounting import preview_repayment_journal_entry
from erpnext_extensions.facility_management.facility_settings_doc import get_facility_settings_doc


def prepare_active_facility():
	frappe.set_user("Administrator")
	company = frappe.db.get_value("Company", {}, "name", order_by="creation asc")
	settings = get_facility_settings_doc(company)
	bank = frappe.db.get_value("Bank", {}, "name", order_by="creation asc")
	fac = frappe.new_doc("Facility")
	fac.facility_name = f"E2E Repay {random_string(5)}"
	fac.company = company
	fac.bank = bank
	fac.contract_date = today()
	fac.receive_date = today()
	fac.principal_amount = 50000
	fac.profit_amount = 5000
	for fn in (
		"default_bank_account",
		"default_loan_payable_account",
		"default_deferred_loan_interest_account",
		"default_interest_expense_account",
		"default_penalty_expense_account",
		"default_cost_center",
	):
		if settings and settings.get(fn):
			target = fn.replace("default_", "")
			fac.set(target, settings.get(fn))
	fac.insert(ignore_permissions=True)
	frappe.db.commit()
	create_receipt_journal_entry(fac.name)
	fac.reload()
	return {"facility": fac.name, "company": company}


def preview_repayment(doc: dict):
	frappe.set_user("Administrator")
	payload = dict(doc)
	payload.setdefault("doctype", "Facility Repayment")
	rep = frappe.get_doc(payload)
	return preview_repayment_journal_entry(rep)


def preview_standard_template():
	prep = prepare_active_facility()
	return preview_repayment(
		{
			"facility": prep["facility"],
			"posting_date": today(),
			"principal_amount": 800,
			"profit_amount": 140,
			"penalty_amount": 60,
		}
	)


def create_draft_repayment_for_e2e():
	prep = prepare_active_facility()
	rep = frappe.new_doc("Facility Repayment")
	rep.facility = prep["facility"]
	rep.posting_date = today()
	rep.principal_amount = 800
	rep.profit_amount = 140
	rep.penalty_amount = 60
	rep.insert(ignore_permissions=True)
	frappe.db.commit()
	return {"facility": prep["facility"], "repayment": rep.name}
