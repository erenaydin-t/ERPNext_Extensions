# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils.caching import request_cache

from erpnext_extensions.iran_accounting.account_explorer.account_hierarchy import (
	account_matches_configured_level,
	code_prefix,
	configured_level_lengths,
	find_account_by_normalized_number,
	is_pure_numeric_code,
	load_company_accounts,
	normalize_account_number,
)
from erpnext_extensions.iran_accounting.account_explorer.account_scope import (
	make_virtual_prefix_key,
	parse_virtual_prefix_key,
)
from erpnext_extensions.iran_accounting.account_explorer.constants import (
	REAL_ACCOUNT_KEY_PREFIX,
	SORTABLE_FIELDS,
	VIRTUAL_UNCLASSIFIED_KEY,
)
from erpnext_extensions.iran_accounting.account_explorer.measures import (
	add_measures,
	finalize_measures,
	row_has_activity,
	zero_measures,
)
from erpnext_extensions.iran_accounting.account_explorer.opening_balance import (
	get_account_wise_measures,
	get_accounts_with_direct_gl_postings,
)
from erpnext_extensions.iran_accounting.account_explorer.pagination import paginate_summary_rows, sort_rows
from erpnext_extensions.iran_accounting.account_explorer.schemas import AccountExplorerQuerySpec


@request_cache
def get_enabled_levels() -> list:
	from erpnext_extensions.iran_accounting.account_explorer.request_cache_helpers import (
		get_iran_accounting_settings,
	)

	settings = get_iran_accounting_settings()
	levels = [row for row in settings.account_explorer_levels or [] if row.enabled]
	return sorted(levels, key=lambda row: int(row.sequence))


def get_default_level_sequence() -> int | None:
	levels = get_enabled_levels()
	return int(levels[0].sequence) if levels else None


def build_account_level_summary(spec: AccountExplorerQuerySpec) -> dict:
	level_sequence = spec.level_sequence or get_default_level_sequence()
	levels = get_enabled_levels()
	level = next((row for row in levels if int(row.sequence) == int(level_sequence)), None)
	if not level:
		frappe.throw(_("No enabled Account Explorer level is configured."))

	accounts = load_company_accounts(spec.company)
	configured_lengths = configured_level_lengths(get_enabled_levels())
	scoped_names = spec.included_account_names or []

	measures_by_account = get_account_wise_measures(spec, scoped_names)
	group_accounts = {name for name in scoped_names if _is_group(accounts, name)}
	direct_posting_groups = get_accounts_with_direct_gl_postings(spec, group_accounts)

	groups: dict[str, dict] = {}
	warnings: list[str] = []

	for account_name in scoped_names:
		row = _row_by_name(accounts, account_name)
		normalized = normalize_account_number(row.get("account_number"))
		account_measures = measures_by_account.get(account_name, zero_measures())

		if not is_pure_numeric_code(normalized):
			group_key = VIRTUAL_UNCLASSIFIED_KEY
		else:
			prefix = code_prefix(normalized, int(level.code_length))
			if not prefix:
				group_key = VIRTUAL_UNCLASSIFIED_KEY
			else:
				if not account_matches_configured_level(normalized, configured_lengths):
					warnings.append(
						_("Account {0} has a code length that does not match configured levels.").format(
							account_name
						)
					)
				group_key = make_virtual_prefix_key(int(level.sequence), prefix)

		group = groups.setdefault(
			group_key,
			{
				"row_key": group_key,
				"display_code": "",
				"display_title": "",
				"is_virtual_group": 1,
				"level_sequence": int(level.sequence),
				"selected_account": None,
				"has_direct_group_posting": 0,
				**zero_measures(),
			},
		)
		add_measures(group, account_measures)

		if account_name in direct_posting_groups:
			group["has_direct_group_posting"] = 1

	_finalize_group_rows(groups, level, accounts, configured_lengths)

	rows = list(groups.values())
	for row in rows:
		finalize_measures(row)

	if spec.hide_zero_rows:
		rows = [row for row in rows if row_has_activity(row)]

	rows = sort_rows(rows, spec, SORTABLE_FIELDS)
	result = paginate_summary_rows(rows, spec)
	result["warnings"] = sorted(set(warnings))
	result["level_sequence"] = int(level.sequence)
	result["level_title"] = level.title
	return result


def _finalize_group_rows(groups: dict, level, accounts: list[dict], configured_lengths: set[int]) -> None:
	for group_key, group in groups.items():
		if group_key == VIRTUAL_UNCLASSIFIED_KEY:
			group.update(
				{
					"row_key": VIRTUAL_UNCLASSIFIED_KEY,
					"display_code": "__UNCLASSIFIED__",
					"display_title": _("Unclassified"),
					"is_virtual_group": 1,
				}
			)
			continue

		parsed = parse_virtual_prefix_key(group_key)
		if not parsed:
			continue
		_level_sequence, prefix = parsed
		real = find_account_by_normalized_number(accounts, prefix)
		if real and is_pure_numeric_code(prefix) and len(prefix) == int(level.code_length):
			group.update(
				{
					"row_key": f"{REAL_ACCOUNT_KEY_PREFIX}:{real.name}",
					"display_code": prefix,
					"display_title": real.account_name or real.name,
					"is_virtual_group": 0,
					"selected_account": real.name,
					"is_group": 1 if real.is_group else 0,
				}
			)
		else:
			group.update(
				{
					"display_code": prefix,
					"display_title": prefix,
					"is_virtual_group": 1,
					"selected_account": None,
				}
			)


def _row_by_name(accounts: list[dict], name: str) -> dict:
	for row in accounts:
		if row.name == name:
			return row
	return {}


def _is_group(accounts: list[dict], name: str) -> bool:
	row = _row_by_name(accounts, name)
	return bool(row.get("is_group"))
