"""Shared context provisioning for cheque_purpose tests and E2E."""

from __future__ import annotations

import frappe
from frappe.utils import now_datetime


def _group_account(company: str, root_type: str) -> str:
	name = frappe.db.get_value(
		"Account",
		{"company": company, "is_group": 1, "root_type": root_type},
		"name",
		order_by="lft asc",
	)
	if not name:
		frappe.throw(f"No group Account root_type={root_type} for {company}")
	return name


def _ensure_account(company: str, parent: str, account_name: str, *, account_type: str | None = None) -> str:
	exists = frappe.db.get_value("Account", {"company": company, "account_name": account_name}, "name")
	if exists:
		return exists
	acc = frappe.new_doc("Account")
	acc.company = company
	acc.parent_account = parent
	acc.account_name = account_name
	acc.is_group = 0
	if account_type:
		acc.account_type = account_type
	acc.insert(ignore_permissions=True)
	return acc.name


def _ensure_bank() -> str:
	name = frappe.db.get_value("Bank", {}, "name", order_by="creation asc")
	if name:
		return name
	bank = frappe.new_doc("Bank")
	bank.bank_name = f"E2E Bank {now_datetime().strftime('%H%M%S')}"
	bank.insert(ignore_permissions=True)
	return bank.name


def _ensure_bank_account(company: str, bank_gl: str, bank: str) -> str:
	ba = frappe.db.get_value(
		"Bank Account",
		{"company": company, "disabled": 0, "is_company_account": 1},
		"name",
		order_by="modified desc",
	)
	if ba:
		return ba
	ba = frappe.db.get_value("Bank Account", {"company": company, "disabled": 0}, "name")
	if ba:
		return ba
	doc = frappe.new_doc("Bank Account")
	doc.account_name = f"E2E BA {company[:20]}"
	doc.bank = bank
	doc.company = company
	doc.is_company_account = 1
	doc.account = bank_gl
	doc.insert(ignore_permissions=True)
	return doc.name


def _ensure_pdc_settings(company: str, ci_hand: str, ci_clear: str, pool: str, protested: str) -> str:
	name = frappe.db.get_value("PDC Settings", {"company": company}, "name") or company
	doc = (
		frappe.get_doc("PDC Settings", name)
		if frappe.db.exists("PDC Settings", name)
		else frappe.new_doc("PDC Settings")
	)
	doc.company = company
	doc.name = name
	doc.default_cheques_in_hand_account = ci_hand
	doc.default_cheques_in_clearing_account = ci_clear
	doc.default_payable_cheque_account = pool
	doc.default_protested_account = protested
	doc.allow_endorsement = 1
	doc.require_sayad_registration = 0
	if frappe.db.exists("PDC Settings", name):
		doc.save(ignore_permissions=True)
	else:
		doc.insert(ignore_permissions=True)
	return doc.name


def _ensure_party(doctype: str, party_name: str) -> str:
	if frappe.db.exists(doctype, party_name):
		return party_name
	doc = frappe.new_doc(doctype)
	if doctype == "Customer":
		doc.customer_name = party_name
		doc.customer_type = "Individual"
		doc.customer_group = (
			frappe.db.get_value("Customer Group", {"is_group": 0}, "name", order_by="lft asc")
			or "All Customer Groups"
		)
		doc.territory = (
			frappe.db.get_value("Territory", {"is_group": 0}, "name", order_by="lft asc") or "All Territories"
		)
	else:
		doc.supplier_name = party_name
		doc.supplier_type = "Individual"
		doc.supplier_group = (
			frappe.db.get_value("Supplier Group", {}, "name", order_by="lft asc") or "All Supplier Groups"
		)
	doc.insert(ignore_permissions=True)
	return doc.name


def _pick_company() -> str:
	"""Prefer a non-_Test company that already has a Bank Account or Chart of Accounts."""
	row = frappe.db.sql(
		"""
		SELECT c.name
		FROM `tabCompany` c
		WHERE c.name NOT LIKE '\\_Test%%'
		  AND EXISTS (
		    SELECT 1 FROM `tabAccount` a WHERE a.company = c.name AND a.is_group = 0 LIMIT 1
		  )
		ORDER BY
		  (SELECT COUNT(*) FROM `tabBank Account` ba WHERE ba.company = c.name AND IFNULL(ba.disabled,0)=0) DESC,
		  c.creation ASC
		LIMIT 1
		""",
		as_list=True,
	)
	if row:
		return row[0][0]
	company = frappe.db.get_value("Company", {"name": ("not like", "_Test%")}, "name", order_by="creation asc")
	if not company:
		frappe.throw("No usable Company for cheque purpose tests")
	return company


def ensure_cheque_purpose_context() -> dict:
	"""Return company/customer/supplier/bank_account/settings with masters created as needed."""
	frappe.set_user("Administrator")
	company = _pick_company()
	asset = _group_account(company, "Asset")
	liab = _group_account(company, "Liability")
	bank_gl = _ensure_account(company, asset, "E2E Purpose Bank GL", account_type="Bank")
	ci_hand = _ensure_account(company, asset, "E2E Purpose Cheques in Hand")
	ci_clear = _ensure_account(company, asset, "E2E Purpose Cheques in Clearing")
	pool = _ensure_account(company, liab, "E2E Purpose Payable Pool")
	protested = _ensure_account(company, asset, "E2E Purpose Protested")
	bank = _ensure_bank()
	bank_account = _ensure_bank_account(company, bank_gl, bank)
	_ensure_pdc_settings(company, ci_hand, ci_clear, pool, protested)
	customer = _ensure_party("Customer", "E2E Purpose Customer")
	supplier = _ensure_party("Supplier", "E2E Purpose Supplier")
	from erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque import (
		_get_pdc_settings_for_company,
	)

	settings = _get_pdc_settings_for_company(company)
	return {
		"company": company,
		"customer": customer,
		"supplier": supplier,
		"bank_account": bank_account,
		"bank_gl": bank_gl,
		"drawer_bank": bank,
		"settings": settings,
	}
