# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

import frappe
from frappe import _

from erpnext_extensions.iran_accounting.account_explorer.constants import NATIVE_PARTY_TYPES


def get_enabled_party_sources() -> list:
	settings = frappe.get_single("Iran Accounting Settings")
	rows = [row for row in settings.account_explorer_party_sources or [] if row.enabled]
	return sorted(rows, key=lambda row: int(row.sequence))


def get_enabled_party_types() -> list[str]:
	return [row.party_type for row in get_enabled_party_sources()]


def get_party_source_config(party_type: str):
	for row in get_enabled_party_sources():
		if row.party_type == party_type:
			return row
	return None


def get_identifier_warnings() -> list[str]:
	warnings: list[str] = []
	for row in get_enabled_party_sources():
		if not row.identifier_field:
			continue
		meta = frappe.get_meta(row.party_type)
		if not meta.has_field(row.identifier_field):
			warnings.append(
				_("Identifier field {0} is missing on {1}.").format(row.identifier_field, row.party_type)
			)
	return warnings


def get_party_identifier(party_type: str, party: str, identifier_field: str | None) -> str | None:
	if not identifier_field or not party:
		return None
	meta = frappe.get_meta(party_type)
	if not meta.has_field(identifier_field):
		return None
	return frappe.db.get_value(party_type, party, identifier_field)


def get_party_display_title(party_type: str, party: str) -> str:
	if party_type in ("Customer", "Supplier"):
		if party_type == "Customer":
			naming = frappe.get_single_value("Selling Settings", "cust_master_name")
			name_field = "customer_name"
		else:
			naming = frappe.db.get_single_value("Buying Settings", "supp_master_name")
			name_field = "supplier_name"
		if naming == "Naming Series":
			return frappe.db.get_value(party_type, party, name_field) or party
		return party
	if party_type == "Employee":
		return frappe.db.get_value("Employee", party, "employee_name") or party
	if party_type == "Shareholder":
		return frappe.db.get_value("Shareholder", party, "title") or party
	return party


def validate_party_type(party_type: str) -> None:
	if party_type not in NATIVE_PARTY_TYPES:
		frappe.throw(_("Unsupported party type {0}.").format(party_type))
