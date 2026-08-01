# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint

from erpnext_extensions.consignment_stock.accounting import (
	force_expense_account_on_items,
	get_consignment_settings,
	resolve_warehouse_account,
	validate_consignment_warehouse,
)


def get_material_loan_settings(company: str):
	return get_consignment_settings(company)


def require_material_loan_accounts(settings) -> None:
	if not settings.get("material_loan_temporary_clearing_account"):
		frappe.throw(
			_("Material Loan Temporary Clearing Account is required for company {0}.").format(
				settings.company
			)
		)
	if not settings.get("material_loan_valuation_difference_account"):
		frappe.throw(
			_("Material Loan Valuation Difference Account is required for company {0}.").format(
				settings.company
			)
		)


def get_temporary_clearing_account(company: str) -> str:
	settings = get_material_loan_settings(company)
	require_material_loan_accounts(settings)
	return settings.material_loan_temporary_clearing_account


def get_valuation_difference_account(company: str) -> str:
	settings = get_material_loan_settings(company)
	require_material_loan_accounts(settings)
	return settings.material_loan_valuation_difference_account


def validate_material_loan_settings(settings) -> None:
	company = settings.company
	temp = settings.get("material_loan_temporary_clearing_account")
	diff = settings.get("material_loan_valuation_difference_account")

	if temp:
		_validate_clearing_or_diff_account(
			temp, company, _("Material Loan Temporary Clearing Account"), check_warehouse_link=True
		)
	if diff:
		_validate_clearing_or_diff_account(
			diff, company, _("Material Loan Valuation Difference Account"), check_warehouse_link=False
		)

	for fieldname, label in (
		("default_material_loan_source_warehouse", _("Default Material Loan Source Warehouse")),
		("default_material_loan_return_warehouse", _("Default Material Loan Return Warehouse")),
	):
		wh = settings.get(fieldname)
		if wh:
			validate_consignment_warehouse(wh, company)

	from erpnext_extensions.consignment_stock.material_loan.party_account import (
		validate_party_account_rows,
	)

	validate_party_account_rows(settings)


def _validate_clearing_or_diff_account(
	account: str, company: str, label: str, *, check_warehouse_link: bool
) -> None:
	meta = frappe.db.get_value(
		"Account",
		account,
		["company", "is_group", "disabled", "account_type", "account_currency"],
		as_dict=True,
	)
	if not meta:
		frappe.throw(_("{0} {1} does not exist.").format(label, account))
	if meta.company != company:
		frappe.throw(_("{0} {1} does not belong to company {2}.").format(label, account, company))
	if cint(meta.is_group):
		frappe.throw(_("{0} {1} cannot be a group account.").format(label, account))
	if cint(meta.disabled):
		frappe.throw(_("{0} {1} is disabled.").format(label, account))
	if meta.account_type == "Stock":
		frappe.throw(_("{0} {1} must not be a Stock account.").format(label, account))
	if check_warehouse_link and frappe.db.exists("Warehouse", {"account": account, "company": company}):
		frappe.throw(_("{0} {1} must not be linked to a Warehouse.").format(label, account))

	company_currency = frappe.get_cached_value("Company", company, "default_currency")
	if meta.account_currency and company_currency and meta.account_currency != company_currency:
		frappe.throw(
			_("{0} {1} currency {2} must match company currency {3}.").format(
				label, account, meta.account_currency, company_currency
			)
		)


def force_temporary_clearing_on_items(doc) -> None:
	force_expense_account_on_items(doc, get_temporary_clearing_account(doc.company))


def validate_loan_warehouses(doc) -> None:
	warehouses = set()
	for row in doc.get("items") or []:
		if row.s_warehouse:
			warehouses.add(row.s_warehouse)
		if row.t_warehouse:
			warehouses.add(row.t_warehouse)
	if not warehouses:
		frappe.throw(_("Material Loan Stock Entry must have a warehouse on every item row."))
	for wh in warehouses:
		resolve_warehouse_account(wh, doc.company)
