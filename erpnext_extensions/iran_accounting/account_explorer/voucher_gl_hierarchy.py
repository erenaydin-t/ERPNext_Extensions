# Copyright (c) 2026, Farbod Siyahpoosh and contributors
"""Batch account hierarchy + GL row grouping for Voucher GL Print.

Hierarchy uses configured Account Explorer levels (code lengths) resolved
against company Account.account_number titles. Root/level-1 may be omitted.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import frappe
from frappe.utils import cint, cstr, flt

from erpnext_extensions.iran_accounting.account_explorer.account_hierarchy import (
	code_prefix,
	find_account_by_normalized_number,
	load_company_accounts,
	normalize_account_number,
)
from erpnext_extensions.iran_accounting.account_explorer.query_builder import get_enabled_levels


PERSON_PARTY_TYPES = frozenset({"Employee", "Student", "Shareholder", "Member"})


def get_hierarchy_start_level(filters: dict | None = None) -> int:
	filters = filters or {}
	if filters.get("account_hierarchy_start_level") is not None:
		return max(1, cint(filters.get("account_hierarchy_start_level")) or 2)
	setting = frappe.get_single_value("Iran Accounting Settings", "voucher_gl_hierarchy_start_level")
	return max(1, cint(setting) or 2)


def should_show_account_hierarchy(filters: dict | None = None) -> bool:
	filters = filters or {}
	if "show_account_hierarchy" in filters:
		return bool(cint(filters.get("show_account_hierarchy")))
	val = frappe.get_single_value("Iran Accounting Settings", "voucher_gl_show_account_hierarchy")
	if val is None or cstr(val).strip() == "":
		return True
	return bool(cint(val))


def should_show_party_breakdown(filters: dict | None = None) -> bool:
	filters = filters or {}
	if "show_party_breakdown" in filters:
		return bool(cint(filters.get("show_party_breakdown")))
	val = frappe.get_single_value("Iran Accounting Settings", "voucher_gl_show_party_breakdown")
	if val is None or cstr(val).strip() == "":
		return True
	return bool(cint(val))


def should_show_dimension_breakdown(filters: dict | None = None) -> bool:
	filters = filters or {}
	if "show_dimension_breakdown" in filters:
		return bool(cint(filters.get("show_dimension_breakdown")))
	val = frappe.get_single_value("Iran Accounting Settings", "voucher_gl_show_dimension_breakdown")
	if val is None or cstr(val).strip() == "":
		return True
	return bool(cint(val))


def should_show_group_subtotals(filters: dict | None = None, *, layout: str = "Standard") -> bool:
	filters = filters or {}
	if "show_group_subtotals" in filters:
		return bool(cint(filters.get("show_group_subtotals")))
	val = frappe.get_single_value("Iran Accounting Settings", "voucher_gl_show_group_subtotals")
	if val is None or cstr(val).strip() == "":
		# Default ON for Standard/Modern/Audit, OFF for Compact.
		return cstr(layout) != "Compact"
	return bool(cint(val))


def _enabled_levels_from_start(start_level: int) -> list[dict]:
	levels = get_enabled_levels() or []
	out = []
	for row in levels:
		seq = cint(row.sequence)
		if seq < start_level:
			continue
		out.append(
			{
				"sequence": seq,
				"code_length": cint(row.code_length),
				"title": cstr(row.title or ""),
				"title_fa": cstr(getattr(row, "title_fa", None) or row.title or ""),
			}
		)
	out.sort(key=lambda r: (r["code_length"], r["sequence"]))
	return out


def build_account_number_index(accounts: list[dict]) -> dict[str, dict]:
	index: dict[str, dict] = {}
	for row in accounts:
		normalized = normalize_account_number(row.get("account_number"))
		if normalized and normalized not in index:
			index[normalized] = row
	return index


def resolve_account_hierarchy_for_number(
	normalized: str,
	*,
	levels: list[dict],
	number_index: dict[str, dict],
	leaf_account: dict | None = None,
) -> list[dict]:
	"""Build hierarchy nodes from start level through leaf.

	Uses configured code lengths validated as prefixes of the leaf number.
	Titles come from Account rows matching each prefix (batch index).
	"""
	hierarchy: list[dict] = []
	seen_numbers: set[str] = set()
	if not normalized:
		if leaf_account:
			return [
				{
					"level_sequence": levels[-1]["sequence"] if levels else 0,
					"account": leaf_account.get("name") or "",
					"account_number": cstr(leaf_account.get("account_number") or ""),
					"account_name": cstr(leaf_account.get("account_name") or leaf_account.get("name") or ""),
				}
			]
		return []

	for level in levels:
		length = cint(level["code_length"])
		if length <= 0:
			continue
		prefix = code_prefix(normalized, length)
		if not prefix:
			continue
		if prefix in seen_numbers:
			continue
		# Only emit levels that are true prefixes (not longer than leaf).
		if len(prefix) > len(normalized):
			continue
		seen_numbers.add(prefix)
		match = number_index.get(prefix)
		# Exact leaf: prefer concrete leaf account meta when numbers match.
		if prefix == normalized and leaf_account:
			match = leaf_account
		if not match and length == len(normalized) and leaf_account:
			match = leaf_account
		account_name = ""
		account_name_key = ""
		if match:
			account_name = cstr(match.get("account_name") or "")
			account_name_key = cstr(match.get("name") or "")
		# Skip empty-title synthetic parents only when no account exists for prefix
		# and this is not the leaf.
		if not account_name and prefix != normalized:
			# Keep code-only parent if a parent account exists without name (rare).
			if not match:
				continue
		hierarchy.append(
			{
				"level_sequence": cint(level["sequence"]),
				"account": account_name_key,
				"account_number": prefix,
				"account_name": account_name or prefix,
			}
		)

	# Ensure leaf is present even for non-standard / non-numeric depths.
	if normalized and normalized not in seen_numbers:
		hierarchy.append(
			{
				"level_sequence": levels[-1]["sequence"] if levels else 0,
				"account": (leaf_account or {}).get("name") or "",
				"account_number": normalized
				if normalized.isdigit()
				else cstr((leaf_account or {}).get("account_number") or ""),
				"account_name": cstr(
					(leaf_account or {}).get("account_name")
					or (leaf_account or {}).get("name")
					or normalized
				),
			}
		)
	# De-dupe consecutive identical account numbers.
	deduped: list[dict] = []
	for node in hierarchy:
		if deduped and deduped[-1]["account_number"] == node["account_number"]:
			continue
		deduped.append(node)
	return deduped


def batch_resolve_account_hierarchies(
	company: str,
	account_names: set[str],
	*,
	start_level: int = 2,
) -> dict[str, list[dict]]:
	"""One company Account load + in-memory prefix/title resolution (no N+1)."""
	if not company or not account_names:
		return {}
	accounts = load_company_accounts(company)
	by_name = {cstr(row.get("name") if hasattr(row, "get") else row.name): row for row in accounts}
	number_index = build_account_number_index(accounts)
	levels = _enabled_levels_from_start(start_level)
	cache: dict[str, list[dict]] = {}
	for name in account_names:
		row = by_name.get(name)
		account_number = ""
		account_name = ""
		if row:
			account_number = row.get("account_number") if hasattr(row, "get") else row.account_number
			account_name = row.get("account_name") if hasattr(row, "get") else row.account_name
		normalized = normalize_account_number(account_number) if row else ""
		if not normalized and row:
			# Missing account_number fallback: single leaf node.
			cache[name] = [
				{
					"level_sequence": levels[-1]["sequence"] if levels else 0,
					"account": name,
					"account_number": "",
					"account_name": cstr(account_name or name),
				}
			]
			continue
		cache[name] = resolve_account_hierarchy_for_number(
			normalized,
			levels=levels,
			number_index=number_index,
			leaf_account=row,
		)
	return cache


def _dimension_grouping_key(row: dict) -> tuple:
	dims = row.get("dimensions") or {}
	parts = []
	for fieldname in sorted(dims.keys()):
		info = dims.get(fieldname) or {}
		parts.append((fieldname, cstr(info.get("value") or "")))
	# Also include native top-level fields for stability.
	parts.append(("cost_center", cstr(row.get("cost_center") or "")))
	parts.append(("project", cstr(row.get("project") or "")))
	return tuple(parts)


def _party_block(row: dict) -> dict | None:
	party = cstr(row.get("party") or "").strip()
	party_type = cstr(row.get("party_type") or "").strip()
	party_name = cstr(row.get("party_name") or party).strip()
	if not party and not party_name:
		return None
	block = {
		"kind": "person" if party_type in PERSON_PARTY_TYPES else "party",
		"party_type": party_type,
		"party": party,
		"party_name": party_name or party,
	}
	return block


def _dimension_lines(row: dict, *, rtl: bool = False) -> list[dict]:
	lines = []
	dims = row.get("dimensions") or {}
	for fieldname, info in dims.items():
		value = cstr((info or {}).get("title") or (info or {}).get("value") or "").strip()
		if not value:
			continue
		label = cstr((info or {}).get("label_fa") if rtl else None) or cstr(
			(info or {}).get("label") or fieldname
		)
		# Prefer label_fa from discovery if present on nested payload.
		if rtl and (info or {}).get("label_fa"):
			label = cstr(info.get("label_fa"))
		lines.append({"fieldname": fieldname, "label": label, "value": value})
	return lines


def resolve_row_description(row: dict, header: dict | None = None) -> dict:
	"""Description priority without unnecessary repetition."""
	header = header or {}
	main = cstr(row.get("remarks") or "").strip()
	detail = cstr(row.get("voucher_detail_no") or "").strip()
	against = cstr(row.get("against") or "").strip()
	voucher_remarks = cstr(header.get("voucher_remarks") or "").strip()
	if not main and voucher_remarks:
		main = voucher_remarks
	reference_parts = []
	if detail:
		reference_parts.append(detail)
	if against and against != main:
		reference_parts.append(against)
	reference = " · ".join(reference_parts)
	return {"main": main, "reference": reference}


def group_print_rows(
	rows: list[dict],
	*,
	show_party: bool = True,
	show_dimensions: bool = True,
	show_subtotals: bool = True,
) -> list[dict]:
	"""Build hierarchical display nodes from flat GL rows.

	Node types:
	  - account_header
	  - party_header
	  - dimension_header (optional when multiple dim combos)
	  - gl_line
	  - party_subtotal / account_subtotal
	"""
	# Group by account then party then dimensions preserving first-seen order.
	account_order: list[str] = []
	by_account: dict[str, list[dict]] = defaultdict(list)
	for row in rows:
		account = cstr(row.get("account") or "")
		if account not in by_account:
			account_order.append(account)
		by_account[account].append(row)

	nodes: list[dict] = []
	for account in account_order:
		account_rows = by_account[account]
		sample = account_rows[0]
		hierarchy = sample.get("account_hierarchy") or []
		nodes.append(
			{
				"node_type": "account_header",
				"account": account,
				"account_hierarchy": hierarchy,
				"account_code": sample.get("account_code"),
				"account_name": sample.get("account_name"),
			}
		)

		party_buckets: dict[tuple, list[dict]] = defaultdict(list)
		party_order: list[tuple] = []
		for row in account_rows:
			if show_party:
				key = (cstr(row.get("party_type") or ""), cstr(row.get("party") or ""))
			else:
				key = ("", "")
			if key not in party_buckets:
				party_order.append(key)
			party_buckets[key].append(row)

		account_debit = 0.0
		account_credit = 0.0
		for party_key in party_order:
			party_rows = party_buckets[party_key]
			party_block = _party_block(party_rows[0]) if show_party else None
			if party_block:
				nodes.append(
					{
						"node_type": "party_header",
						"party": party_block,
						"account": account,
					}
				)

			dim_buckets: dict[tuple, list[dict]] = defaultdict(list)
			dim_order: list[tuple] = []
			for row in party_rows:
				dkey = _dimension_grouping_key(row) if show_dimensions else ()
				if dkey not in dim_buckets:
					dim_order.append(dkey)
				dim_buckets[dkey].append(row)

			party_debit = 0.0
			party_credit = 0.0
			for dkey in dim_order:
				group_rows = dim_buckets[dkey]
				dim_lines = _dimension_lines(group_rows[0]) if show_dimensions else []
				# Emit dimension header only when more than one dim combo under party
				# or when dims exist.
				if show_dimensions and dim_lines and len(dim_order) > 1:
					nodes.append(
						{
							"node_type": "dimension_header",
							"dimensions": dim_lines,
							"account": account,
							"party": party_block,
						}
					)

				group_debit = 0.0
				group_credit = 0.0
				for row in group_rows:
					debit = flt(row.get("debit"))
					credit = flt(row.get("credit"))
					group_debit += debit
					group_credit += credit
					party_debit += debit
					party_credit += credit
					account_debit += debit
					account_credit += credit
					line_dims = dim_lines if show_dimensions else _dimension_lines(row)
					# For single dim combo, attach dims on the line.
					if show_dimensions and len(dim_order) == 1:
						line_dims = _dimension_lines(row)
					nodes.append(
						{
							"node_type": "gl_line",
							"row": row,
							"account": account,
							"account_hierarchy": hierarchy,
							"party": party_block,
							"dimensions": line_dims if show_dimensions else [],
							"description": resolve_row_description(row),
							"debit": debit,
							"credit": credit,
							"line_amount": debit or credit,
						}
					)

				if show_subtotals and len(group_rows) > 1 and show_dimensions and len(dim_order) > 1:
					nodes.append(
						{
							"node_type": "dimension_subtotal",
							"account": account,
							"party": party_block,
							"dimensions": dim_lines,
							"debit": group_debit,
							"credit": group_credit,
						}
					)

			if show_subtotals and party_block and len(party_rows) > 1:
				nodes.append(
					{
						"node_type": "party_subtotal",
						"account": account,
						"party": party_block,
						"debit": party_debit,
						"credit": party_credit,
					}
				)

		if show_subtotals and len(account_rows) > 1:
			nodes.append(
				{
					"node_type": "account_subtotal",
					"account": account,
					"account_hierarchy": hierarchy,
					"account_code": sample.get("account_code"),
					"account_name": sample.get("account_name"),
					"debit": account_debit,
					"credit": account_credit,
				}
			)

	return nodes


def enrich_rows_with_hierarchy(
	payload: dict,
	filters: dict | None = None,
) -> dict:
	"""Mutate payload rows with account_hierarchy; attach grouped display nodes."""
	filters = filters or {}
	header = payload.get("header") or {}
	company = header.get("company") or filters.get("company")
	rows = payload.get("rows") or []
	if not rows:
		payload["display_nodes"] = []
		return payload

	show_hierarchy = should_show_account_hierarchy(filters)
	start_level = get_hierarchy_start_level(filters)
	layout = cstr(filters.get("layout") or payload.get("layout") or "Standard")

	if show_hierarchy and company:
		names = {cstr(r.get("account")) for r in rows if r.get("account")}
		cache = batch_resolve_account_hierarchies(company, names, start_level=start_level)
		for row in rows:
			row["account_hierarchy"] = cache.get(cstr(row.get("account")), [])
	else:
		for row in rows:
			row["account_hierarchy"] = [
				{
					"level_sequence": 0,
					"account": row.get("account") or "",
					"account_number": cstr(row.get("account_code") or ""),
					"account_name": cstr(row.get("account_name") or ""),
				}
			]

	# Attach FA labels onto dimension payloads when discovery provided them.
	for row in rows:
		for fieldname, info in (row.get("dimensions") or {}).items():
			if not isinstance(info, dict):
				continue
			# Preserve existing labels; layout may overlay FA.

	payload["display_nodes"] = group_print_rows(
		rows,
		show_party=should_show_party_breakdown(filters),
		show_dimensions=should_show_dimension_breakdown(filters),
		show_subtotals=should_show_group_subtotals(filters, layout=layout),
	)
	return payload
