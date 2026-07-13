# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

"""Resolve GL accounts, Bank master, and Facility Settings for tests and live E2E."""

from __future__ import annotations

import frappe
from frappe.utils import random_string

from erpnext_extensions.facility_management.facility_settings_doc import (
	get_facility_settings_doc,
	populate_facility_settings_template_defaults,
)


def ensure_bank_master(*, label: str | None = None) -> str:
	bank = frappe.db.get_value("Bank", {}, "name", order_by="modified desc")
	if bank:
		return bank
	doc = frappe.new_doc("Bank")
	doc.bank_name = label or f"Facility E2E Bank {random_string(4)}"
	doc.insert(ignore_permissions=True)
	return doc.name


def ensure_company_bank_gl_account(company: str) -> str:
	account = frappe.db.get_value(
		"Account",
		{"company": company, "account_type": "Bank", "is_group": 0},
		"name",
		order_by="modified desc",
	)
	if account:
		return account
	parent = frappe.db.get_value(
		"Account",
		{"company": company, "account_type": "Bank", "is_group": 1},
		"name",
		order_by="modified desc",
	)
	if not parent:
		frappe.throw(f"No Bank group account for company {company}")
	abbr = frappe.get_cached_value("Company", company, "abbr") or company
	account_name = f"Facility E2E Bank GL - {abbr}"
	if frappe.db.exists("Account", account_name):
		return account_name
	doc = frappe.new_doc("Account")
	doc.account_name = "Facility E2E Bank GL"
	doc.parent_account = parent
	doc.company = company
	doc.account_type = "Bank"
	doc.is_group = 0
	doc.insert(ignore_permissions=True)
	return doc.name


def resolve_facility_gl_accounts(company: str) -> dict[str, str | None]:
	bank_gl = ensure_company_bank_gl_account(company)

	def _pick_liability(company: str, *, exclude: set[str] | None = None) -> str | None:
		exclude = exclude or set()
		for row in frappe.get_all(
			"Account",
			filters={"company": company, "root_type": "Liability", "is_group": 0},
			fields=["name", "account_type"],
			order_by="modified desc",
			limit=50,
		):
			if row.name in exclude:
				continue
			if (row.account_type or "") in ("Payable", "Receivable"):
				continue
			return row.name
		return None

	loan_payable = _pick_liability(company)
	if not loan_payable:
		loan_payable = frappe.db.get_value(
			"Account",
			{"company": company, "root_type": "Liability", "is_group": 0},
			"name",
			order_by="modified desc",
		)
	deferred = _pick_liability(company, exclude={loan_payable} if loan_payable else set())
	if not deferred:
		deferred = frappe.db.get_value(
			"Account",
			{"company": company, "root_type": "Expense", "is_group": 0},
			"name",
			order_by="modified desc",
		)
	interest = frappe.db.get_value(
		"Account",
		{"company": company, "root_type": "Expense", "is_group": 0},
		"name",
		order_by="modified desc",
	)
	penalty = (
		frappe.db.get_value(
			"Account",
			{"company": company, "root_type": "Expense", "is_group": 0, "name": ("!=", interest)},
			"name",
			order_by="modified desc",
		)
		or interest
	)
	cost_center = frappe.db.get_value(
		"Cost Center", {"company": company, "is_group": 0}, "name", order_by="modified desc"
	)
	bank_master = frappe.db.get_value("Bank", {}, "name", order_by="modified desc")
	bank_account_dim = frappe.db.get_value(
		"Bank Account", {"company": company}, "name", order_by="modified desc"
	)
	return {
		"company": company,
		"bank": bank_master,
		"bank_gl": bank_gl,
		"loan_payable": loan_payable,
		"deferred": deferred,
		"interest": interest,
		"penalty": penalty,
		"cost_center": cost_center,
		"bank_dimension": bank_master,
		"bank_account_dimension": bank_account_dim,
	}


def ensure_facility_settings_accounts(company: str, accounts: dict[str, str | None]) -> None:
	name = frappe.db.get_value("Facility Settings", {"company": company}, "name")
	if name:
		doc = frappe.get_doc("Facility Settings", name)
	else:
		doc = frappe.new_doc("Facility Settings")
		doc.company = company
	fieldmap = {
		"default_bank_account": accounts.get("bank_gl"),
		"default_loan_payable_account": accounts.get("loan_payable"),
		"default_deferred_loan_interest_account": accounts.get("deferred"),
		"default_interest_expense_account": accounts.get("interest"),
		"default_penalty_expense_account": accounts.get("penalty"),
		"default_cost_center": accounts.get("cost_center"),
		"default_bank_dimension": accounts.get("bank_dimension"),
		"default_bank_account_dimension": accounts.get("bank_account_dimension"),
	}
	for fn, val in fieldmap.items():
		if val and not doc.get(fn):
			doc.set(fn, val)
	populate_facility_settings_template_defaults(doc)
	doc.save(ignore_permissions=True)


def apply_facility_test_accounts(facility, *, company: str | None = None) -> dict[str, str | None]:
	"""Fill Facility + Facility Settings with resolvable GL accounts (tests / E2E)."""
	company = company or facility.company
	accounts = resolve_facility_gl_accounts(company)
	missing = [k for k in ("bank_gl", "loan_payable", "deferred", "interest") if not accounts.get(k)]
	if missing:
		frappe.throw(f"Cannot resolve facility test accounts for {company}: missing {missing}")
	ensure_facility_settings_accounts(company, accounts)
	settings = get_facility_settings_doc(company)
	for fac_fn, key in (
		("bank_account", "bank_gl"),
		("loan_payable_account", "loan_payable"),
		("deferred_loan_interest_account", "deferred"),
		("interest_expense_account", "interest"),
		("penalty_expense_account", "penalty"),
		("cost_center", "cost_center"),
		("bank_dimension", "bank_dimension"),
		("bank_account_dimension", "bank_account_dimension"),
	):
		if not facility.get(fac_fn):
			val = accounts.get(key) or (settings.get(f"default_{fac_fn}") if settings else None)
			if val:
				facility.set(fac_fn, val)
	if not facility.get("bank"):
		facility.bank = accounts.get("bank") or ensure_bank_master()
	return accounts


def site_e2e_context() -> dict[str, str | None]:
	frappe.set_user("Administrator")
	company = frappe.db.get_value("Company", {"name": ("!=", "")}, "name", order_by="creation asc")
	if not company:
		frappe.throw("No Company")
	accounts = resolve_facility_gl_accounts(company)
	accounts["bank"] = ensure_bank_master()
	accounts["bank_dimension"] = accounts["bank"]
	if not all([accounts.get("bank_gl"), accounts.get("loan_payable"), accounts.get("deferred")]):
		frappe.throw(f"Missing GL accounts for E2E: {accounts}")
	ensure_facility_settings_accounts(company, accounts)
	return accounts
