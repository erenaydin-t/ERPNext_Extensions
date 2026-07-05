# Copyright (c) 2026, ERPNext Extensions contributors

from __future__ import annotations

import frappe
from frappe.utils import flt, today

from erpnext_extensions.facility_management.doctype.facility.facility import create_receipt_journal_entry
from erpnext_extensions.facility_management.facility_accounting import (
	create_and_submit_repayment_je,
	preview_repayment_journal_entry,
)
from erpnext_extensions.facility_management.e2e.facility_repayment_je_prep import prepare_active_facility

REPAYMENT_ACCOUNTS_AND_DIMENSIONS = (
	"bank_account",
	"loan_payable_account",
	"deferred_loan_interest_account",
	"interest_expense_account",
	"penalty_expense_account",
	"cost_center",
	"department",
	"bank_dimension",
	"bank_account_dimension",
)


def _alternate_account(company: str, current: str | None, *, root_type: str) -> str | None:
	filters = {"company": company, "root_type": root_type, "is_group": 0}
	if current:
		filters["name"] = ("!=", current)
	return frappe.db.get_value("Account", filters, "name", order_by="modified desc")


def build_repayment_override_values(facility_name: str) -> dict[str, str]:
	"""Pick alternate GL accounts (same company) for integration / E2E override tests."""
	fac = frappe.get_doc("Facility", facility_name)
	company = fac.company
	out: dict[str, str] = {}
	pairs = [
		("bank_account", "Asset"),
		("loan_payable_account", "Liability"),
		("deferred_loan_interest_account", "Liability"),
		("interest_expense_account", "Expense"),
		("penalty_expense_account", "Expense"),
	]
	for fn, root in pairs:
		cur = fac.get(fn)
		alt = _alternate_account(company, cur, root_type=root)
		if alt:
			out[fn] = alt
		elif cur:
			out[fn] = cur
	for fn in ("cost_center", "department", "bank_dimension", "bank_account_dimension"):
		val = fac.get(fn)
		if val:
			out[fn] = val
	return out


def run_repayment_override_integration() -> dict:
	"""Integration: defaults from Facility, overrides on Repayment, preview + submit JE."""
	frappe.set_user("Administrator")
	prep = prepare_active_facility()
	facility_name = prep["facility"]
	fac = frappe.get_doc("Facility", facility_name)
	overrides = build_repayment_override_values(facility_name)

	rep = frappe.new_doc("Facility Repayment")
	rep.facility = facility_name
	rep.posting_date = today()
	rep.principal_amount = 500
	rep.profit_amount = 100
	rep.penalty_amount = 50
	rep.insert(ignore_permissions=True)
	for fn, val in overrides.items():
		rep.set(fn, val)
	rep.save(ignore_permissions=True)

	prev = preview_repayment_journal_entry(rep)
	je_accounts = {row["account"] for row in prev.get("rows") or []}
	missing = [overrides[fn] for fn in ("bank_account", "loan_payable_account") if overrides.get(fn) not in je_accounts]

	rep.submit()
	je_name = rep.journal_entry
	je = frappe.get_doc("Journal Entry", je_name)
	submitted_accounts = {row.account for row in je.accounts}
	missing_submit = [
		overrides[fn] for fn in overrides if fn.endswith("_account") and overrides[fn] not in submitted_accounts
	]

	ok = not missing and not missing_submit
	if overrides.get("interest_expense_account") and overrides["interest_expense_account"] not in submitted_accounts:
		ok = False

	return {
		"ok": ok,
		"repayment": rep.name,
		"facility": facility_name,
		"overrides": overrides,
		"preview_accounts": sorted(je_accounts),
		"je_accounts": sorted(submitted_accounts),
		"missing_preview": missing,
		"missing_submit": missing_submit,
		"je": je_name,
	}


def prepare_repayment_draft_override_e2e() -> dict:
	"""Playwright prep: draft repayment with facility defaults then override map for desk edits."""
	frappe.set_user("Administrator")
	frappe.clear_cache()
	frappe.reload_doctype("Facility Repayment")
	prep = prepare_active_facility()
	facility_name = prep["facility"]
	overrides = build_repayment_override_values(facility_name)
	rep = frappe.new_doc("Facility Repayment")
	rep.facility = facility_name
	rep.posting_date = today()
	rep.principal_amount = 400
	rep.profit_amount = 80
	rep.penalty_amount = 20
	rep.insert(ignore_permissions=True)
	frappe.db.commit()
	return {
		"facility": facility_name,
		"repayment": rep.name,
		"overrides": overrides,
		"company": prep["company"],
	}
