# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

import frappe
from frappe import _

from erpnext_extensions.iran_accounting.account_explorer.constants import (
	UNIFIED_PARTY_SORTABLE_FIELDS,
	VIRTUAL_UNIFIED_UNMAPPED_KEY,
)
from erpnext_extensions.iran_accounting.account_explorer.measures import measures_from_opening_period
from erpnext_extensions.iran_accounting.account_explorer.pagination import paginate_summary_rows, sort_rows
from erpnext_extensions.iran_accounting.account_explorer.party_sources import get_identifier_warnings
from erpnext_extensions.iran_accounting.account_explorer.schemas import AccountExplorerQuerySpec
from erpnext_extensions.iran_accounting.account_explorer.unified_party_opening import (
	get_party_opening_balances,
	get_party_period_balances,
	rollup_measures_for_members,
)
from erpnext_extensions.iran_accounting.account_explorer.unified_party_registry import (
	get_active_unified_parties,
	get_member_tuples,
	get_mapped_member_keys,
	get_uap_members,
	get_unified_party_types,
	resolve_uap_for_company,
)


def build_unified_party_summary(spec: AccountExplorerQuerySpec) -> dict:
	party_types = get_unified_party_types()
	if not party_types:
		return _empty_result(spec)

	if spec.unified_party_scope.selected_unified_party:
		return _build_selected_uap_summary(spec)

	opening = get_party_opening_balances(spec, party_types)
	period = get_party_period_balances(spec, party_types)
	rows: list[dict] = []

	for uap in get_active_unified_parties(spec.company):
		members = get_member_tuples(uap.name)
		if not members:
			continue
		opening_debit, opening_credit, period_debit, period_credit = rollup_measures_for_members(
			members, opening, period
		)
		rows.append(
			{
				"row_key": f"unified_party:{uap.name}",
				"unified_party": uap.name,
				"display_code": uap.name,
				"display_title": uap.unified_name,
				"member_count": len(members),
				"primary_member_label": _primary_member_label(uap.name),
				"identifier_summary": uap.primary_identifier or "",
				"is_virtual_group": 0,
				"drill_down_enabled": 1,
				**measures_from_opening_period(
					opening_debit, opening_credit, period_debit, period_credit
				),
			}
		)

	# v4.6.2: unmapped/empty unified-party buckets are excluded from grid + totals.
	# Backend helper `_build_unmapped_row` remains for diagnostics / direct callers.

	rows = sort_rows(rows, spec, UNIFIED_PARTY_SORTABLE_FIELDS)
	result = paginate_summary_rows(rows, spec)
	result["warnings"] = sorted(set(get_identifier_warnings()))
	return result


def build_unified_party_member_breakdown(spec: AccountExplorerQuerySpec) -> dict:
	uap_name = spec.unified_party_scope.selected_unified_party
	if not uap_name:
		return {"rows": [], "totals": {}, "warnings": []}

	party_types = get_unified_party_types()
	opening = get_party_opening_balances(spec, party_types)
	period = get_party_period_balances(spec, party_types)
	rows: list[dict] = []
	for member in get_uap_members(uap_name):
		key = (member.party_type, member.party)
		opening_debit, opening_credit = opening.get(key, (0.0, 0.0))
		period_debit, period_credit = period.get(key, (0.0, 0.0))
		rows.append(
			{
				"row_key": f"member:{member.party_type}:{member.party}",
				"party_type": member.party_type,
				"party": member.party,
				"display_code": member.party,
				"display_title": member.party_display_name or member.party,
				"party_identifier": member.identifier_value,
				"is_primary": int(member.is_primary or 0),
				**measures_from_opening_period(
					opening_debit, opening_credit, period_debit, period_credit
				),
			}
		)
	return {
		"rows": rows,
		"unified_party": uap_name,
		"warnings": sorted(set(get_identifier_warnings())),
	}


def _build_selected_uap_summary(spec: AccountExplorerQuerySpec) -> dict:
	uap_name = spec.unified_party_scope.selected_unified_party
	uap = resolve_uap_for_company(uap_name, spec.company)
	if not uap:
		return _empty_result(spec)

	members = get_member_tuples(uap_name)
	party_types = get_unified_party_types()
	opening = get_party_opening_balances(spec, party_types)
	period = get_party_period_balances(spec, party_types)
	opening_debit, opening_credit, period_debit, period_credit = rollup_measures_for_members(
		members, opening, period
	)
	rows = [
		{
			"row_key": f"unified_party:{uap_name}",
			"unified_party": uap_name,
			"display_code": uap_name,
			"display_title": uap.unified_name,
			"member_count": len(members),
			"primary_member_label": _primary_member_label(uap_name),
			"identifier_summary": uap.primary_identifier or "",
			"is_virtual_group": 0,
			"drill_down_enabled": 1,
			**measures_from_opening_period(opening_debit, opening_credit, period_debit, period_credit),
		}
	]
	result = paginate_summary_rows(rows, spec)
	result["warnings"] = sorted(set(get_identifier_warnings()))
	return result


def _build_unmapped_row(spec, opening, period, mapped_keys):
	party_types = get_unified_party_types()
	keys = set(opening.keys()) | set(period.keys())
	unmapped_keys = [key for key in keys if key not in mapped_keys and key[0] in party_types]
	if not unmapped_keys:
		return None
	opening_debit = opening_credit = period_debit = period_credit = 0.0
	for key in unmapped_keys:
		open_vals = opening.get(key, (0.0, 0.0))
		period_vals = period.get(key, (0.0, 0.0))
		opening_debit += open_vals[0]
		opening_credit += open_vals[1]
		period_debit += period_vals[0]
		period_credit += period_vals[1]
	return {
		"row_key": VIRTUAL_UNIFIED_UNMAPPED_KEY,
		"unified_party": "",
		"display_code": "__UNMAPPED__",
		"display_title": _("Unmapped Parties"),
		"member_count": len(unmapped_keys),
		"primary_member_label": "",
		"identifier_summary": "",
		"is_virtual_group": 1,
		"drill_down_enabled": 0,
		**measures_from_opening_period(opening_debit, opening_credit, period_debit, period_credit),
	}


def _primary_member_label(uap_name: str) -> str:
	members = get_uap_members(uap_name)
	primary = next((row for row in members if row.is_primary), None)
	if not primary and members:
		primary = members[0]
	if not primary:
		return ""
	return f"{primary.party_type}: {primary.party_display_name or primary.party}"


def _empty_result(spec: AccountExplorerQuerySpec) -> dict:
	result = paginate_summary_rows([], spec)
	result["warnings"] = sorted(set(get_identifier_warnings()))
	return result
