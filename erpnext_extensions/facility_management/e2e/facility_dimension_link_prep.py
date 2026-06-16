"""Prep company / Facility Settings for dimension Link E2E."""

from __future__ import annotations

import frappe
from frappe.utils import nowdate, random_string

from erpnext_extensions.facility_management.facility_settings_doc import (
	populate_facility_settings_template_defaults,
)


def prepare():
	frappe.set_user("Administrator")
	company = frappe.db.get_value("Company", {}, "name", order_by="creation asc")
	if not company:
		frappe.throw("No Company on site")

	bank = frappe.db.get_value("Bank", {}, "name", order_by="creation asc")
	if not bank:
		frappe.throw("No Bank on site")

	fs_name = frappe.db.get_value("Facility Settings", {"company": company}, "name")
	if fs_name:
		doc = frappe.get_doc("Facility Settings", fs_name)
	else:
		doc = frappe.new_doc("Facility Settings")
		doc.company = company
		populate_facility_settings_template_defaults(doc)
		doc.insert(ignore_permissions=True)
		fs_name = doc.name
		frappe.db.commit()

	return {
		"company": company,
		"bank": bank,
		"facility_settings_name": fs_name,
		"facility_name": f"E2E Dim {random_string(6)}",
		"today": nowdate(),
	}


def insert_api_facility_with_defaults():
	"""Server/API path: insert without manual accounts; validate fills from settings."""
	frappe.set_user("Administrator")
	company = frappe.db.get_value("Company", {}, "name", order_by="creation asc")
	bank = frappe.db.get_value("Bank", {}, "name", order_by="creation asc")
	fs = frappe.db.get_value("Facility Settings", {"company": company}, "name")
	doc = frappe.new_doc("Facility")
	doc.facility_name = f"API Defaults {random_string(6)}"
	doc.company = company
	doc.bank = bank
	doc.contract_date = nowdate()
	doc.principal_amount = 5000
	doc.profit_amount = 500
	doc.is_opening_facility = 1
	doc.insert(ignore_permissions=True)
	frappe.db.commit()
	return {"name": doc.name, "bank_account": doc.bank_account, "settings": fs}


def get_company_without_facility_settings():
	"""Return a company name that has no Facility Settings row (for E2E)."""
	frappe.set_user("Administrator")
	for name in frappe.get_all("Company", pluck="name", order_by="creation desc"):
		if not frappe.db.exists("Facility Settings", {"company": name}):
			return {"company": name}

	abbr = f"NF{random_string(4).upper()}"
	company_name = f"E2E No Facility Settings {random_string(4)}"
	doc = frappe.get_doc(
		{
			"doctype": "Company",
			"company_name": company_name,
			"abbr": abbr,
			"default_currency": frappe.db.get_single_value("Global Defaults", "default_currency") or "IRR",
			"country": frappe.db.get_single_value("Global Defaults", "country") or "Iran",
		}
	)
	doc.insert(ignore_permissions=True)
	frappe.db.commit()
	return {"company": doc.name}
