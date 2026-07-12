# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

import frappe
from frappe import _

from erpnext_extensions.iran_accounting.account_explorer.party_sources import (
	get_party_display_title,
	get_party_identifier,
)
from erpnext_extensions.iran_accounting.account_explorer.unified_party_registry import (
	get_mapped_member_keys,
	get_unified_party_sources,
	normalize_identifier,
	normalize_identifier_digits,
)


def build_unified_party_suggestions(*, company: str | None = None, limit: int = 50) -> dict:
	limit = max(1, min(int(limit or 50), 200))
	sources = get_unified_party_sources()
	mapped = get_mapped_member_keys(company)
	groups: dict[str, dict] = {}

	for source in sources:
		if not source.identifier_field:
			continue
		meta = frappe.get_meta(source.party_type)
		if not meta.has_field(source.identifier_field):
			continue
		parties = frappe.get_all(
			source.party_type,
			fields=["name", source.identifier_field],
			limit=5000,
		)
		for row in parties:
			party = row.name
			identifier = row.get(source.identifier_field)
			if not identifier:
				continue
			key = (source.party_type, party)
			if key in mapped:
				continue
			norm = normalize_identifier(identifier)
			digit_norm = normalize_identifier_digits(identifier)
			group_key = digit_norm or norm
			if not group_key:
				continue
			entry = groups.setdefault(
				group_key,
				{
					"match_key": group_key,
					"identifier_field": source.identifier_field,
					"members": [],
				},
			)
			if len(entry["members"]) >= 20:
				continue
			entry["members"].append(
				{
					"party_type": source.party_type,
					"party": party,
					"display_title": get_party_display_title(source.party_type, party),
					"identifier": get_party_identifier(source.party_type, party, source.identifier_field),
				}
			)

	suggestions = []
	for entry in groups.values():
		members = entry["members"]
		if len(members) < 2:
			continue
		party_types = {member["party_type"] for member in members}
		if len(party_types) < 2 and len(members) < 2:
			continue
		suggestions.append(
			{
				"match_key": entry["match_key"],
				"identifier_field": entry["identifier_field"],
				"suggested_name": members[0]["display_title"],
				"members": members,
			}
		)

	suggestions.sort(key=lambda row: row["match_key"])
	return {
		"suggestions": suggestions[:limit],
		"warnings": [_("Suggestions are informational only and do not create mappings automatically.")],
	}
