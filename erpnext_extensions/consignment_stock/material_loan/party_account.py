# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint


def validate_party_for_tracking(party_type: str | None, party: str | None) -> None:
	if not party_type or not party:
		frappe.throw(_("Material Loan Party Type and Party are required."))
	if not frappe.db.exists("Party Type", party_type):
		frappe.throw(_("Party Type {0} does not exist.").format(party_type))
	account_type = frappe.get_cached_value("Party Type", party_type, "account_type")
	if account_type not in ("Payable", "Receivable"):
		frappe.throw(
			_("Party Type {0} must have account type Payable or Receivable.").format(party_type)
		)
	if not frappe.db.exists(party_type, party):
		frappe.throw(_("{0} {1} does not exist.").format(party_type, party))


def validate_party_account_rows(settings) -> None:
	seen = set()
	company = settings.company
	default_recv = frappe.get_cached_value("Company", company, "default_receivable_account")
	default_pay = frappe.get_cached_value("Company", company, "default_payable_account")

	for row in settings.get("material_loan_party_accounts") or []:
		if not row.party_type or not row.account:
			frappe.throw(_("Material Loan Party Account rows require Party Type and Account."))
		if row.party_type in seen:
			frappe.throw(
				_("Duplicate Material Loan Party Account mapping for Party Type {0}.").format(
					row.party_type
				)
			)
		seen.add(row.party_type)
		_validate_mapped_account(
			row.account,
			company,
			row.party_type,
			default_recv=default_recv,
			default_pay=default_pay,
		)


def resolve_material_loan_party_account(party_type: str, company: str) -> str:
	settings = frappe.get_cached_doc(
		"Consignment Stock Settings",
		frappe.db.get_value("Consignment Stock Settings", {"company": company}, "name"),
	)
	for row in settings.get("material_loan_party_accounts") or []:
		if row.party_type == party_type:
			_validate_mapped_account(
				row.account,
				company,
				party_type,
				default_recv=frappe.get_cached_value("Company", company, "default_receivable_account"),
				default_pay=frappe.get_cached_value("Company", company, "default_payable_account"),
			)
			return row.account
	frappe.throw(
		_("No Material Loan Party Account mapping for Party Type {0} in company {1}.").format(
			party_type, company
		)
	)


def _validate_mapped_account(
	account: str,
	company: str,
	party_type: str,
	*,
	default_recv: str | None,
	default_pay: str | None,
) -> None:
	meta = frappe.db.get_value(
		"Account",
		account,
		["company", "is_group", "disabled", "account_type", "account_currency"],
		as_dict=True,
	)
	if not meta:
		frappe.throw(_("Material Loan Party Account {0} does not exist.").format(account))
	if meta.company != company:
		frappe.throw(
			_("Material Loan Party Account {0} does not belong to company {1}.").format(
				account, company
			)
		)
	if cint(meta.is_group):
		frappe.throw(_("Material Loan Party Account {0} cannot be a group.").format(account))
	if cint(meta.disabled):
		frappe.throw(_("Material Loan Party Account {0} is disabled.").format(account))
	if meta.account_type == "Stock":
		frappe.throw(_("Material Loan Party Account {0} must not be a Stock account.").format(account))
	if frappe.db.exists("Warehouse", {"account": account, "company": company}):
		frappe.throw(
			_("Material Loan Party Account {0} must not be linked to a Warehouse.").format(account)
		)

	expected = frappe.get_cached_value("Party Type", party_type, "account_type")
	if meta.account_type != expected:
		frappe.throw(
			_(
				"Material Loan Party Account {0} type {1} must match Party Type {2} account type {3}."
			).format(account, meta.account_type, party_type, expected)
		)

	if party_type == "Customer" and meta.account_type != "Receivable":
		frappe.throw(_("Customer Material Loan account must be Receivable."))
	if party_type == "Supplier" and meta.account_type != "Payable":
		frappe.throw(_("Supplier Material Loan account must be Payable."))

	if account in (default_recv, default_pay):
		frappe.throw(
			_(
				"Material Loan Party Account {0} must not be the company default Debtors or Creditors account."
			).format(account)
		)

	company_currency = frappe.get_cached_value("Company", company, "default_currency")
	if meta.account_currency and company_currency and meta.account_currency != company_currency:
		frappe.throw(
			_("Material Loan Party Account {0} currency must match company currency.").format(account)
		)
