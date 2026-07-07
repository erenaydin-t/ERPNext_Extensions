"""E2E prep for Facility Type and facility_name JE templates."""

from __future__ import annotations

import frappe
from frappe.utils import random_string, today

from erpnext_extensions.facility_management.facility_e2e_context import apply_facility_test_accounts
from erpnext_extensions.facility_management.facility_settings_doc import (
	FACILITY_SETTINGS_TEMPLATE_DEFAULTS,
	LEGACY_FACILITY_SETTINGS_TEMPLATE_DEFAULTS,
	get_facility_settings_doc,
)


def ensure_type_master():
	frappe.set_user("Administrator")
	from erpnext_extensions.facility_management.facility_type_data import (
		DEFAULT_FACILITY_TYPES,
		ensure_default_facility_types,
	)

	ensure_default_facility_types()
	return {"types": len(DEFAULT_FACILITY_TYPES)}


def template_migration_sample():
	frappe.set_user("Administrator")
	company = frappe.db.get_value("Company", {}, "name", order_by="creation asc")
	settings = get_facility_settings_doc(company)
	if not settings:
		return {"skipped": True}
	stock = settings.get("default_repayment_remarks_template") or ""
	legacy = LEGACY_FACILITY_SETTINGS_TEMPLATE_DEFAULTS["default_repayment_remarks_template"]
	new = FACILITY_SETTINGS_TEMPLATE_DEFAULTS["default_repayment_remarks_template"]
	return {
		"uses_facility_name": "{facility_name}" in stock,
		"matches_new_default": stock.strip() == new.strip(),
		"legacy_was": legacy,
		"current": stock,
	}


def prepare_facility_for_template_e2e():
	frappe.set_user("Administrator")
	company = frappe.db.get_value("Company", {}, "name", order_by="creation asc")
	settings = get_facility_settings_doc(company)
	bank = frappe.db.get_value("Bank", {}, "name", order_by="creation asc")
	ft = "سرمایه در گردش"
	if not frappe.db.exists("Facility Type", ft):
		doc = frappe.new_doc("Facility Type")
		doc.facility_type_name = ft
		doc.insert(ignore_permissions=True)
	fac = frappe.new_doc("Facility")
	fac.facility_name = "وام سرمایه در گردش نمونه"
	fac.facility_type = ft
	fac.company = company
	fac.bank = bank
	fac.contract_date = today()
	fac.receive_date = today()
	fac.principal_amount = 8000
	fac.profit_amount = 1000
	apply_facility_test_accounts(fac, company=company)
	fac.insert(ignore_permissions=True)
	frappe.db.commit()
	from erpnext_extensions.facility_management.doctype.facility.facility import create_receipt_journal_entry

	create_receipt_journal_entry(fac.name)
	frappe.db.commit()
	return {
		"facility": fac.name,
		"facility_name": fac.facility_name,
		"facility_type": ft,
		"company": company,
	}


def create_draft_repayment_for_facility(facility: str):
	frappe.set_user("Administrator")
	rep = frappe.new_doc("Facility Repayment")
	rep.facility = facility
	rep.posting_date = today()
	rep.principal_amount = 800
	rep.profit_amount = 140
	rep.penalty_amount = 60
	rep.insert(ignore_permissions=True)
	frappe.db.commit()
	return {"repayment": rep.name, "facility": facility}


def prepare_facility_with_repayment_draft():
	prep = prepare_facility_for_template_e2e()
	from erpnext_extensions.facility_management.doctype.facility.facility import create_receipt_journal_entry

	create_receipt_journal_entry(prep["facility"])
	rep = create_draft_repayment_for_facility(prep["facility"])
	prep["repayment"] = rep["repayment"]
	return prep
