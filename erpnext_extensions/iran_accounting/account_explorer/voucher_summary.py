# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

import frappe
from frappe.query_builder.functions import Count, Min, Sum
from frappe.utils import flt

from erpnext_extensions.iran_accounting.account_explorer.constants import VOUCHER_SORTABLE_FIELDS
from erpnext_extensions.iran_accounting.account_explorer.gle_filters import (
	apply_document_scope_filters,
	apply_opening_entry_filters,
	apply_scoped_gle_filters,
	collect_scope_warnings,
)
from erpnext_extensions.iran_accounting.account_explorer.pagination import sort_rows
from erpnext_extensions.iran_accounting.account_explorer.party_sources import resolve_party_display_name
from erpnext_extensions.iran_accounting.account_explorer.schemas import AccountExplorerQuerySpec
from erpnext_extensions.iran_accounting.account_explorer.voucher_metadata import enrich_voucher_rows


def build_voucher_summary(spec: AccountExplorerQuerySpec) -> dict:
	scoped_rows = _aggregate_vouchers(spec, scoped=True)
	full_totals = _aggregate_vouchers(spec, scoped=False)
	full_map = {
		(row["voucher_type"], row["voucher_no"]): row for row in full_totals if row.get("voucher_no")
	}

	rows: list[dict] = []
	for row in scoped_rows:
		voucher_type = row.get("voucher_type")
		voucher_no = row.get("voucher_no")
		if not voucher_type or not voucher_no:
			continue
		scoped_debit = flt(row.get("scoped_debit"))
		scoped_credit = flt(row.get("scoped_credit"))
		full_row = full_map.get((voucher_type, voucher_no), {})
		party_type = row.get("party_type") or ""
		party = row.get("party") or ""
		rows.append(
			{
				"row_key": f"voucher:{voucher_type}:{voucher_no}",
				"posting_date": str(row.get("posting_date") or ""),
				"voucher_type": voucher_type,
				"voucher_no": voucher_no,
				"party_type": party_type,
				"party": party,
				"party_name": _party_name(party_type, party),
				"voucher_title": voucher_no,
				"reference": None,
				"scoped_debit": scoped_debit,
				"scoped_credit": scoped_credit,
				"scoped_net": scoped_debit - scoped_credit,
				"full_voucher_debit": flt(full_row.get("scoped_debit")),
				"full_voucher_credit": flt(full_row.get("scoped_credit")),
				"has_multiple_parties": int(row.get("party_count", 0) > 1),
				"is_virtual_group": 0,
				"drill_down_enabled": 1,
			}
		)

	enrich_voucher_rows(rows)

	if spec.hide_zero_rows:
		rows = [
			row
			for row in rows
			if flt(row.get("scoped_debit")) or flt(row.get("scoped_credit"))
		]

	rows = sort_rows(rows, spec, VOUCHER_SORTABLE_FIELDS)
	total_rows = len(rows)
	page = spec.pagination.page
	page_size = spec.pagination.page_size
	offset = (page - 1) * page_size

	return {
		"rows": rows[offset : offset + page_size],
		"totals": _sum_voucher_totals(rows),
		"pagination": {
			"page": page,
			"page_size": page_size,
			"total_rows": total_rows,
			"has_next": offset + page_size < total_rows,
		},
		"warnings": collect_scope_warnings(spec),
	}


def _sum_voucher_totals(rows: list[dict]) -> dict:
	scoped_debit = sum(flt(row.get("scoped_debit")) for row in rows)
	scoped_credit = sum(flt(row.get("scoped_credit")) for row in rows)
	return {
		"scoped_debit": scoped_debit,
		"scoped_credit": scoped_credit,
		"scoped_net": scoped_debit - scoped_credit,
	}


def _aggregate_vouchers(spec: AccountExplorerQuerySpec, *, scoped: bool) -> list[dict]:
	gle = frappe.qb.DocType("GL Entry")
	query = frappe.qb.from_(gle).select(
		gle.voucher_type,
		gle.voucher_no,
		Min(gle.posting_date).as_("posting_date"),
		Sum(gle.debit).as_("scoped_debit"),
		Sum(gle.credit).as_("scoped_credit"),
	)
	if scoped:
		query = apply_scoped_gle_filters(query, gle, spec)
	else:
		query = apply_document_scope_filters(query, gle, spec)

	query = (
		query.where(gle.voucher_type.isnotnull())
		.where(gle.voucher_no.isnotnull())
		.where(gle.voucher_no != "")
		.where(gle.posting_date >= spec.from_date)
		.where(gle.posting_date <= spec.to_date)
	)
	query = apply_opening_entry_filters(query, gle, spec)
	query = query.groupby(gle.company, gle.voucher_type, gle.voucher_no)

	rows = query.run(as_dict=True)
	_enrich_party_fields(spec, rows, scoped=scoped)
	return rows


def _enrich_party_fields(spec: AccountExplorerQuerySpec, rows: list[dict], *, scoped: bool) -> None:
	if not rows:
		return
	keys = [(row.voucher_type, row.voucher_no) for row in rows]
	gle = frappe.qb.DocType("GL Entry")
	query = frappe.qb.from_(gle).select(
		gle.voucher_type,
		gle.voucher_no,
		gle.party_type,
		gle.party,
		Count(gle.name).as_("line_count"),
	)
	if scoped:
		query = apply_scoped_gle_filters(query, gle, spec)
	else:
		query = apply_document_scope_filters(query, gle, spec)
	query = (
		query.where(gle.party.isnotnull())
		.where(gle.party != "")
		.where(gle.posting_date >= spec.from_date)
		.where(gle.posting_date <= spec.to_date)
	)
	query = apply_opening_entry_filters(query, gle, spec)
	query = query.groupby(gle.voucher_type, gle.voucher_no, gle.party_type, gle.party)

	party_rows = query.run(as_dict=True)
	party_map: dict[tuple[str, str], dict] = {}
	for row in party_rows:
		key = (row.voucher_type, row.voucher_no)
		entry = party_map.setdefault(key, {"parties": set(), "party_type": row.party_type, "party": row.party})
		entry["parties"].add((row.party_type, row.party))

	for row in rows:
		key = (row.voucher_type, row.voucher_no)
		party_info = party_map.get(key, {})
		parties = party_info.get("parties") or set()
		row["party_count"] = len(parties)
		row["party_type"] = party_info.get("party_type") or ""
		row["party"] = party_info.get("party") or ""


def _party_name(party_type: str, party: str) -> str:
	"""Resolve party display name without querying missing columns."""
	if not party_type or not party:
		return ""
	cache_key = f"{party_type}:{party}"
	cache = getattr(_party_name, "_cache", None)
	if cache is None:
		cache = {}
		_party_name._cache = cache
	cached = cache.get(cache_key)
	if cached is not None:
		return cached
	value = resolve_party_display_name(party_type, party) or party
	cache[cache_key] = value
	return value
