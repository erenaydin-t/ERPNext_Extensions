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


# Preferred display fields for native ERPNext party doctypes.
PARTY_DISPLAY_FIELD_MAP = {
	"Customer": "customer_name",
	"Supplier": "supplier_name",
	"Employee": "employee_name",
	"Shareholder": "title",
}

_GENERIC_PARTY_DISPLAY_CANDIDATES = (
	"title",
	"customer_name",
	"supplier_name",
	"employee_name",
	"party_name",
)


def _safe_party_field_value(party_type: str, party: str, fieldname: str) -> str | None:
	"""Return field value only when the column exists — never SELECT a missing field."""
	if not party_type or not party or not fieldname:
		return None
	if not frappe.db.exists("DocType", party_type):
		return None
	meta = frappe.get_meta(party_type)
	if not meta.has_field(fieldname):
		return None
	return frappe.db.get_value(party_type, party, fieldname)


def resolve_party_display_name(party_type: str, party: str) -> str:
	"""Safe party display name for Voucher Summary / GL / Print.

	Never queries a non-existent column. Falls back to party id.
	"""
	if not party_type or not party:
		return ""
	preferred = PARTY_DISPLAY_FIELD_MAP.get(party_type)
	if preferred:
		value = _safe_party_field_value(party_type, party, preferred)
		if value:
			return value
		return party
	if not frappe.db.exists("DocType", party_type):
		return party
	meta = frappe.get_meta(party_type)
	for candidate in _GENERIC_PARTY_DISPLAY_CANDIDATES:
		if meta.has_field(candidate):
			value = frappe.db.get_value(party_type, party, candidate)
			if value:
				return value
	return party


def get_party_display_title(party_type: str, party: str) -> str:
	"""Party-axis display title (respects Customer/Supplier naming settings)."""
	if party_type in ("Customer", "Supplier"):
		if party_type == "Customer":
			naming = frappe.get_single_value("Selling Settings", "cust_master_name")
			name_field = "customer_name"
		else:
			naming = frappe.db.get_single_value("Buying Settings", "supp_master_name")
			name_field = "supplier_name"
		if naming == "Naming Series":
			return _safe_party_field_value(party_type, party, name_field) or party
		return party
	if party_type in ("Employee", "Shareholder") or party_type not in NATIVE_PARTY_TYPES:
		return resolve_party_display_name(party_type, party)
	return party


def validate_party_type(party_type: str) -> None:
	if party_type not in NATIVE_PARTY_TYPES:
		frappe.throw(_("Unsupported party type {0}.").format(party_type))
