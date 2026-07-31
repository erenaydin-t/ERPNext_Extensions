# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint


def get_consignment_settings(company: str):
	if not company:
		frappe.throw(_("Company is required for Consignment Stock Settings."))
	name = frappe.db.get_value("Consignment Stock Settings", {"company": company}, "name")
	if not name:
		frappe.throw(
			_("Consignment Stock Settings not configured for company {0}.").format(company)
		)
	return frappe.get_cached_doc("Consignment Stock Settings", name)


def validate_settings_accounts(settings) -> None:
	company = settings.company
	for fieldname, label in (
		("consignment_inventory_account", _("Consignment Inventory Account")),
		("consignment_temporary_clearing_account", _("Consignment Temporary Clearing Account")),
		("consignment_valuation_difference_account", _("Consignment Valuation Difference Account")),
	):
		account = settings.get(fieldname)
		if not account:
			continue
		_validate_account(account, company, label)

	temp = settings.get("consignment_temporary_clearing_account")
	if temp:
		account_type = frappe.get_cached_value("Account", temp, "account_type")
		if account_type == "Stock":
			frappe.throw(
				_("Consignment Temporary Clearing Account {0} must not be of type Stock.").format(temp)
			)

	cc = settings.get("default_cost_center")
	if cc:
		cc_company = frappe.get_cached_value("Cost Center", cc, "company")
		if cc_company != company:
			frappe.throw(_("Cost Center {0} does not belong to company {1}.").format(cc, company))
		if cint(frappe.get_cached_value("Cost Center", cc, "is_group")):
			frappe.throw(_("Cost Center {0} cannot be a group.").format(cc))

	wh = settings.get("default_consignment_warehouse")
	if wh:
		wh_company = frappe.get_cached_value("Warehouse", wh, "company")
		if wh_company != company:
			frappe.throw(_("Warehouse {0} does not belong to company {1}.").format(wh, company))


def _validate_account(account: str, company: str, label: str) -> None:
	meta = frappe.db.get_value(
		"Account",
		account,
		["company", "is_group", "disabled", "account_type"],
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


def get_temporary_clearing_account(company: str) -> str:
	return get_consignment_settings(company).consignment_temporary_clearing_account


def get_valuation_difference_account(company: str) -> str:
	return get_consignment_settings(company).consignment_valuation_difference_account


def get_inventory_account(company: str) -> str:
	return get_consignment_settings(company).consignment_inventory_account


def force_expense_account_on_items(doc, account: str) -> None:
	for row in doc.get("items") or []:
		row.expense_account = account


def apply_default_cost_center(doc, settings=None) -> None:
	settings = settings or get_consignment_settings(doc.company)
	cc = settings.default_cost_center
	if not cc:
		return
	for row in doc.get("items") or []:
		if not row.cost_center:
			row.cost_center = cc


def validate_warehouse_inventory_account(doc, settings=None) -> None:
	"""Ensure target/source warehouses use the configured consignment inventory account when set."""
	settings = settings or get_consignment_settings(doc.company)
	expected = settings.consignment_inventory_account
	if not expected:
		return

	from erpnext.stock import get_warehouse_account_map

	wh_map = get_warehouse_account_map(doc.company)
	warehouses = set()
	for row in doc.get("items") or []:
		if row.t_warehouse:
			warehouses.add(row.t_warehouse)
		if row.s_warehouse:
			warehouses.add(row.s_warehouse)

	for wh in warehouses:
		info = wh_map.get(wh) or {}
		account = info.get("account")
		if account and account != expected:
			frappe.throw(
				_(
					"Warehouse {0} inventory account {1} does not match Consignment Inventory Account {2}."
				).format(wh, account, expected)
			)
