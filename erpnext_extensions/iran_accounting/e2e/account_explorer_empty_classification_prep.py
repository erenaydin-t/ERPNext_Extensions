# Copyright (c) 2026, Farbod Siyahpoosh and contributors
"""Prep deterministic GL for Account Explorer empty-classification Playwright gates."""

from __future__ import annotations

import frappe
from frappe.utils import getdate, today

from erpnext_extensions.iran_accounting.tests.test_account_explorer_fixtures import (
	current_fiscal_year,
	enable_wave2a_analysis,
)

MARKER = "AE-EMPTY-CLASS-V462"


def _leaf_accounts(company: str, limit: int = 4) -> list[str]:
	rows = frappe.get_all(
		"Account",
		filters={"company": company, "is_group": 0, "disabled": 0},
		pluck="name",
		limit=limit,
		order_by="name",
	)
	return rows


def _ensure_customer(name: str) -> str:
	if frappe.db.exists("Customer", name):
		return name
	doc = frappe.get_doc(
		{
			"doctype": "Customer",
			"customer_name": name,
			"customer_type": "Company",
			"customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
			or "All Customer Groups",
			"territory": frappe.db.get_value("Territory", {"is_group": 0}, "name") or "All Territories",
		}
	)
	doc.flags.ignore_permissions = True
	doc.insert()
	return doc.name


def _ensure_cost_center(company: str, name: str) -> str:
	existing = frappe.db.get_value("Cost Center", {"company": company, "cost_center_name": name}, "name")
	if existing:
		return existing
	parent = frappe.db.get_value("Cost Center", {"company": company, "is_group": 1}, "name")
	doc = frappe.get_doc(
		{
			"doctype": "Cost Center",
			"cost_center_name": name,
			"company": company,
			"parent_cost_center": parent,
			"is_group": 0,
		}
	)
	doc.flags.ignore_permissions = True
	doc.insert()
	return doc.name


def _cancel_old(company: str) -> None:
	for name in frappe.get_all(
		"Journal Entry",
		filters={"company": company, "user_remark": ("like", f"{MARKER}%"), "docstatus": 1},
		pluck="name",
	):
		doc = frappe.get_doc("Journal Entry", name)
		doc.flags.ignore_permissions = True
		doc.cancel()


def _submit_je(company: str, remark: str, posting_date, lines: list[dict]) -> str:
	je = frappe.new_doc("Journal Entry")
	je.voucher_type = "Journal Entry"
	je.company = company
	je.posting_date = posting_date
	je.user_remark = remark
	for line in lines:
		je.append("accounts", line)
	je.flags.ignore_permissions = True
	je.insert()
	je.submit()
	return je.name


def prepare_empty_classification_e2e(company: str | None = None) -> dict:
	"""Create classified + empty party/dimension movement for UI verification."""
	frappe.connect()
	frappe.set_user("Administrator")
	company = company or "_Test Company"
	if not frappe.db.exists("Company", company):
		frappe.throw(f"Company {company} not found")

	enable_wave2a_analysis()
	fy = current_fiscal_year(company)
	if not fy:
		frappe.throw("No fiscal year")
	fiscal_year, from_date, to_date = fy
	posting_date = getdate(to_date) if getdate(to_date) <= getdate(today()) else getdate(from_date)

	accounts = _leaf_accounts(company, 4)
	if len(accounts) < 4:
		frappe.throw("Need at least 4 leaf accounts")

	receivable = frappe.db.get_value(
		"Account",
		{"company": company, "account_type": "Receivable", "is_group": 0, "disabled": 0},
		"name",
	) or accounts[0]

	customer = _ensure_customer(f"{MARKER} Customer")
	cost_center = _ensure_cost_center(company, f"{MARKER} CC")

	_cancel_old(company)

	classified_party_amount = 100.0
	empty_party_amount = 50.0
	classified_dim_amount = 80.0
	empty_dim_amount = 40.0

	je_party = _submit_je(
		company,
		f"{MARKER}-PARTY-CLASSIFIED",
		posting_date,
		[
			{
				"account": receivable,
				"party_type": "Customer",
				"party": customer,
				"debit_in_account_currency": classified_party_amount,
				"debit": classified_party_amount,
				"cost_center": cost_center,
			},
			{
				"account": accounts[1],
				"credit_in_account_currency": classified_party_amount,
				"credit": classified_party_amount,
				"cost_center": cost_center,
			},
		],
	)
	je_blank_party = _submit_je(
		company,
		f"{MARKER}-PARTY-EMPTY",
		posting_date,
		[
			{
				"account": accounts[2],
				"debit_in_account_currency": empty_party_amount,
				"debit": empty_party_amount,
				"cost_center": cost_center,
			},
			{
				"account": accounts[3],
				"credit_in_account_currency": empty_party_amount,
				"credit": empty_party_amount,
				"cost_center": cost_center,
			},
		],
	)
	je_dim = _submit_je(
		company,
		f"{MARKER}-DIM-CLASSIFIED",
		posting_date,
		[
			{
				"account": accounts[0],
				"debit_in_account_currency": classified_dim_amount,
				"debit": classified_dim_amount,
				"cost_center": cost_center,
			},
			{
				"account": accounts[1],
				"credit_in_account_currency": classified_dim_amount,
				"credit": classified_dim_amount,
				"cost_center": cost_center,
			},
		],
	)
	# Empty dimension: omit cost_center when schema allows; otherwise leave blank string.
	blank_dim_debit = {
		"account": accounts[2],
		"debit_in_account_currency": empty_dim_amount,
		"debit": empty_dim_amount,
	}
	blank_dim_credit = {
		"account": accounts[3],
		"credit_in_account_currency": empty_dim_amount,
		"credit": empty_dim_amount,
	}
	je_blank_dim = _submit_je(
		company,
		f"{MARKER}-DIM-EMPTY",
		posting_date,
		[blank_dim_debit, blank_dim_credit],
	)

	frappe.db.commit()
	return {
		"company": company,
		"fiscal_year": fiscal_year,
		"from_date": str(from_date),
		"to_date": str(to_date),
		"posting_date": str(posting_date),
		"customer": customer,
		"cost_center": cost_center,
		"account": accounts[0],
		"je_party": je_party,
		"je_blank_party": je_blank_party,
		"je_dim": je_dim,
		"je_blank_dim": je_blank_dim,
		"classified_party_amount": classified_party_amount,
		"empty_party_amount": empty_party_amount,
		"expected_party_total_debit": classified_party_amount,
		"classified_dim_amount": classified_dim_amount,
		"empty_dim_amount": empty_dim_amount,
		"expected_dim_total_debit_at_least": classified_dim_amount,
	}
