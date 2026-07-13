# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

import re

import frappe
from frappe import _

from erpnext_extensions.iran_accounting.account_explorer.constants import (
	ARABIC_DIGITS,
	PERSIAN_DIGITS,
)


def normalize_identifier(value: str | None) -> str:
	if not value:
		return ""
	text = str(value).strip().translate(PERSIAN_DIGITS).translate(ARABIC_DIGITS)
	text = re.sub(r"\s+", " ", text)
	return text.casefold()


def normalize_identifier_digits(value: str | None) -> str:
	text = normalize_identifier(value)
	return re.sub(r"\D+", "", text)


def validate_member_uniqueness(
	party_type: str,
	party: str,
	*,
	company: str | None,
	exclude_uap: str | None = None,
) -> None:
	conflict = find_member_conflict(party_type, party, company=company, exclude_uap=exclude_uap)
	if conflict:
		frappe.throw(
			_("Party {0} {1} is already mapped to Unified Accounting Party {2}.").format(
				party_type, party, conflict
			)
		)


def find_member_conflict(
	party_type: str,
	party: str,
	*,
	company: str | None,
	exclude_uap: str | None = None,
) -> str | None:
	conditions = [
		"m.party_type = %s",
		"m.party = %s",
		"u.status = 'Active'",
	]
	params: list = [party_type, party]

	if company:
		conditions.append("(u.company IS NULL OR u.company = '' OR u.company = %s)")
		params.append(company)
	else:
		pass

	if exclude_uap:
		conditions.append("u.name != %s")
		params.append(exclude_uap)

	row = frappe.db.sql(
		f"""
		select u.name
		from `tabUnified Accounting Party Member` m
		inner join `tabUnified Accounting Party` u on u.name = m.parent
		where {" and ".join(conditions)}
		limit 1
		""",
		tuple(params),
		as_dict=True,
	)
	return row[0].name if row else None


def validate_unified_name_uniqueness(unified_name: str, *, exclude_uap: str | None = None) -> None:
	if not unified_name:
		return
	filters = {"status": "Active", "unified_name": unified_name}
	if exclude_uap:
		filters["name"] = ("!=", exclude_uap)
	existing = frappe.db.get_value("Unified Accounting Party", filters, "name")
	if existing:
		frappe.throw(_("An Active Unified Accounting Party with this name already exists: {0}").format(existing))


def get_unified_party_sources():
	from erpnext_extensions.iran_accounting.account_explorer.party_sources import get_enabled_party_sources

	return [row for row in get_enabled_party_sources() if row.show_in_unified_party]


def get_unified_party_types() -> list[str]:
	return [row.party_type for row in get_unified_party_sources()]


def get_active_unified_parties(company: str | None = None) -> list[dict]:
	filters: dict = {"status": "Active"}
	rows = frappe.get_all(
		"Unified Accounting Party",
		filters=filters,
		fields=["name", "unified_name", "unified_name_fa", "company", "member_count", "primary_identifier", "status"],
		order_by="unified_name asc",
	)
	if company:
		rows = [row for row in rows if not row.company or row.company == company]
	return rows


def get_uap_members(uap_name: str) -> list[dict]:
	return frappe.get_all(
		"Unified Accounting Party Member",
		filters={"parent": uap_name},
		fields=["party_type", "party", "party_display_name", "identifier_value", "is_primary", "sequence"],
		order_by="sequence asc, idx asc",
	)


def get_member_tuples(uap_name: str) -> list[tuple[str, str]]:
	return [(row.party_type, row.party) for row in get_uap_members(uap_name) if row.party_type and row.party]


def resolve_uap_for_company(uap_name: str, company: str) -> dict | None:
	uap = frappe.db.get_value(
		"Unified Accounting Party",
		uap_name,
		["name", "unified_name", "company", "status", "primary_identifier"],
		as_dict=True,
	)
	if not uap or uap.status != "Active":
		return None
	if uap.company and uap.company != company:
		return None
	return uap


def build_member_index(company: str | None = None) -> dict[str, list[tuple[str, str]]]:
	index: dict[str, list[tuple[str, str]]] = {}
	for uap in get_active_unified_parties(company):
		index[uap.name] = get_member_tuples(uap.name)
	return index


def build_reverse_member_index(company: str | None = None) -> dict[tuple[str, str], str]:
	reverse: dict[tuple[str, str], str] = {}
	for uap_name, members in build_member_index(company).items():
		for key in members:
			reverse[key] = uap_name
	return reverse


def get_mapped_member_keys(company: str | None = None) -> set[tuple[str, str]]:
	keys: set[tuple[str, str]] = set()
	for members in build_member_index(company).values():
		keys.update(members)
	return keys
