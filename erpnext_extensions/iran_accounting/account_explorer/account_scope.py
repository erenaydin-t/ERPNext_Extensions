# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

import frappe

from erpnext_extensions.iran_accounting.account_explorer.account_hierarchy import (
	code_prefix,
	descendant_accounts,
	is_pure_numeric_code,
	load_company_accounts,
	normalize_account_number,
)
from erpnext_extensions.iran_accounting.account_explorer.constants import (
	VIRTUAL_PREFIX_KEY_PREFIX,
	VIRTUAL_UNCLASSIFIED_KEY,
)
from erpnext_extensions.iran_accounting.account_explorer.schemas import AccountExplorerQuerySpec


def make_virtual_prefix_key(level_sequence: int, prefix: str) -> str:
	return f"{VIRTUAL_PREFIX_KEY_PREFIX}:{level_sequence}:{prefix}"


def parse_virtual_prefix_key(virtual_row_key: str) -> tuple[int, str] | None:
	prefix = f"{VIRTUAL_PREFIX_KEY_PREFIX}:"
	if not virtual_row_key or not virtual_row_key.startswith(prefix):
		return None
	rest = virtual_row_key[len(prefix) :]
	level_str, _, code_prefix = rest.partition(":")
	if not level_str or not code_prefix:
		return None
	try:
		return int(level_str), code_prefix
	except ValueError:
		return None


def resolve_account_scope(spec: AccountExplorerQuerySpec) -> list[str]:
	accounts = load_company_accounts(spec.company)
	tree_root = spec.account_scope.tree_root_account or spec.account_scope.selected_account
	base_names = descendant_accounts(accounts, tree_root)

	if spec.account_scope.virtual_row_key == VIRTUAL_UNCLASSIFIED_KEY:
		return _filter_unclassified_accounts(accounts, base_names, spec)

	parsed = parse_virtual_prefix_key(spec.account_scope.virtual_row_key or "")
	if parsed:
		level_sequence, prefix = parsed
		level = _get_level_by_sequence(level_sequence)
		if not level:
			return base_names
		code_length = int(level.code_length)
		return [
			name
			for name in base_names
			if _account_in_prefix_group(_account_row(accounts, name), code_length, prefix)
		]

	if spec.account_scope.mode == "account" and spec.account_scope.selected_account:
		return descendant_accounts(accounts, spec.account_scope.selected_account)

	return base_names


def _account_row(accounts: list[dict], name: str) -> dict:
	for row in accounts:
		if row.name == name:
			return row
	return {}


def _filter_unclassified_accounts(
	accounts: list[dict], base_names: list[str], spec: AccountExplorerQuerySpec
) -> list[str]:
	levels = _enabled_levels()
	configured_lengths = {int(level.code_length) for level in levels}
	result = []
	for name in base_names:
		row = _account_row(accounts, name)
		normalized = normalize_account_number(row.get("account_number"))
		if not is_pure_numeric_code(normalized):
			result.append(name)
			continue
		if normalized and len(normalized) not in configured_lengths:
			result.append(name)
	return result


def _account_in_prefix_group(row: dict, code_length: int, prefix: str) -> bool:
	normalized = normalize_account_number(row.get("account_number"))
	group_prefix = code_prefix(normalized, code_length)
	return group_prefix == prefix


def _enabled_levels():
	settings = frappe.get_single("Iran Accounting Settings")
	return [row for row in settings.account_explorer_levels or [] if row.enabled]


def _get_level_by_sequence(sequence: int):
	for row in _enabled_levels():
		if int(row.sequence) == int(sequence):
			return row
	return None
