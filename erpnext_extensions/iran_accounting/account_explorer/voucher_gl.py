# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, flt

from erpnext_extensions.iran_accounting.account_explorer.constants import GL_GROUP_SORTABLE_FIELDS
from erpnext_extensions.iran_accounting.account_explorer.gle_filters import (
	apply_opening_entry_filters,
	apply_scoped_gle_filters,
	collect_scope_warnings,
)
from erpnext_extensions.iran_accounting.account_explorer.pagination import sort_rows
from erpnext_extensions.iran_accounting.account_explorer.schemas import AccountExplorerQuerySpec
from erpnext_extensions.iran_accounting.account_explorer.voucher_metadata import enrich_voucher_rows
from erpnext_extensions.iran_accounting.account_explorer.voucher_summary import _party_name


def build_grouped_gl_entries(spec: AccountExplorerQuerySpec) -> dict:
	if not spec.voucher_scope.voucher_type or not spec.voucher_scope.voucher_no:
		frappe.throw(_("Voucher type and voucher number are required for grouped GL detail."))

	dimension_field = spec.dimension_scope.dimension_type
	gle = frappe.qb.DocType("GL Entry")
	select_fields = [gle.account, gle.party_type, gle.party, gle.debit, gle.credit, gle.against]
	if dimension_field:
		select_fields.append(gle[dimension_field].as_("dimension_value"))

	query = frappe.qb.from_(gle).select(*select_fields)
	query = apply_scoped_gle_filters(query, gle, spec)
	query = (
		query.where(gle.posting_date >= spec.from_date)
		.where(gle.posting_date <= spec.to_date)
	)
	query = apply_opening_entry_filters(query, gle, spec)

	groups: dict[tuple, dict] = {}
	for row in query.run(as_dict=True):
		dimension_value = row.get("dimension_value") if dimension_field else None
		key = (row.account, row.party_type or "", row.party or "", dimension_value)
		group = groups.setdefault(
			key,
			{
				"account": row.account,
				"party_type": row.party_type or "",
				"party": row.party or "",
				"dimension_value": dimension_value,
				"debit": 0.0,
				"credit": 0.0,
				"against_values": [],
			},
		)
		group["debit"] += flt(row.debit)
		group["credit"] += flt(row.credit)
		if row.against:
			group["against_values"].append(row.against)

	rows: list[dict] = []
	for group in groups.values():
		account = group["account"]
		party_type = group["party_type"]
		party = group["party"]
		rows.append(
			{
				"row_key": f"glgroup:{spec.voucher_scope.voucher_type}:{spec.voucher_scope.voucher_no}:{account}:{party}",
				"account": account,
				"account_name": frappe.get_cached_value("Account", account, "account_name") or account,
				"party_type": party_type,
				"party": party,
				"party_name": _party_name(party_type, party),
				"dimension_value": group.get("dimension_value"),
				"debit": flt(group["debit"]),
				"credit": flt(group["credit"]),
				"against": _trim_against(group["against_values"]),
			}
		)

	rows = sort_rows(rows, spec, GL_GROUP_SORTABLE_FIELDS)
	max_rows = cint(frappe.get_single_value("Iran Accounting Settings", "max_drill_down_rows")) or 10000
	if len(rows) > max_rows:
		frappe.throw(_("Grouped GL result exceeds the configured maximum ({0} rows).").format(max_rows))

	return {
		"voucher_header": _voucher_header(spec),
		"rows": rows,
		"totals": {
			"debit": sum(flt(row.get("debit")) for row in rows),
			"credit": sum(flt(row.get("credit")) for row in rows),
		},
		"pagination": {
			"page": 1,
			"page_size": len(rows),
			"total_rows": len(rows),
			"has_next": False,
		},
		"warnings": collect_scope_warnings(spec),
	}


def _voucher_header(spec: AccountExplorerQuerySpec) -> dict:
	gle = frappe.qb.DocType("GL Entry")
	row = (
		frappe.qb.from_(gle)
		.select(gle.posting_date, gle.party_type, gle.party)
		.where(gle.company == spec.company)
		.where(gle.voucher_type == spec.voucher_scope.voucher_type)
		.where(gle.voucher_no == spec.voucher_scope.voucher_no)
		.orderby(gle.posting_date)
		.limit(1)
		.run(as_dict=True)
	)
	header = {
		"voucher_type": spec.voucher_scope.voucher_type,
		"voucher_no": spec.voucher_scope.voucher_no,
		"posting_date": None,
		"party_type": None,
		"party": None,
		"voucher_title": spec.voucher_scope.voucher_no,
	}
	if row:
		header["posting_date"] = str(row[0].posting_date)
		header["party_type"] = row[0].party_type
		header["party"] = row[0].party
	enrich_voucher_rows([header])
	return header


def _trim_against(values: list[str], limit: int = 240) -> str:
	unique = []
	seen = set()
	for value in values:
		part = (value or "").strip()
		if not part or part in seen:
			continue
		seen.add(part)
		unique.append(part)
	text = ", ".join(unique)
	return text if len(text) <= limit else text[: limit - 3] + "..."
