# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, flt

from erpnext_extensions.iran_accounting.account_explorer.constants import (
	GL_DIMENSION_EXPAND_THRESHOLD,
	GL_GROUP_SORTABLE_FIELDS,
	gl_dimension_layout_mode,
)
from erpnext_extensions.iran_accounting.account_explorer.dimension_discovery import (
	filter_usable_gl_dimensions,
	get_discovered_dimensions,
)
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

	dimensions = filter_usable_gl_dimensions(get_discovered_dimensions())
	gle = frappe.qb.DocType("GL Entry")
	select_fields = [
		gle.name,
		gle.posting_date,
		gle.account,
		gle.party_type,
		gle.party,
		gle.debit,
		gle.credit,
		gle.account_currency,
		gle.remarks,
	]
	for dimension in dimensions:
		select_fields.append(gle[dimension["fieldname"]])

	query = frappe.qb.from_(gle).select(*select_fields)
	query = apply_scoped_gle_filters(query, gle, spec)
	query = (
		query.where(gle.posting_date >= spec.from_date)
		.where(gle.posting_date <= spec.to_date)
		.where(gle.voucher_type == spec.voucher_scope.voucher_type)
		.where(gle.voucher_no == spec.voucher_scope.voucher_no)
	)
	query = apply_opening_entry_filters(query, gle, spec)

	raw_rows = query.run(as_dict=True)
	max_rows = cint(frappe.get_single_value("Iran Accounting Settings", "max_drill_down_rows")) or 10000
	if len(raw_rows) > max_rows:
		frappe.throw(_("Grouped GL result exceeds the configured maximum ({0} rows).").format(max_rows))

	account_names = _account_name_map({row.account for row in raw_rows if row.account})
	dimension_titles = _dimension_title_maps(dimensions, raw_rows)
	rows: list[dict] = []
	for row in raw_rows:
		account = row.account
		party_type = row.party_type or ""
		party = row.party or ""
		debit = flt(row.debit)
		credit = flt(row.credit)
		dimension_payload = _row_dimensions(dimensions, row, dimension_titles)

		entry = {
			"row_key": f"glentry:{row.name}",
			"posting_date": str(row.posting_date) if row.posting_date else None,
			"account": account,
			"account_name": account_names.get(account) or account,
			"party_type": party_type,
			"party": party,
			"party_name": _party_name(party_type, party),
			"dimensions": dimension_payload,
			"debit": debit,
			"credit": credit,
			"currency": row.account_currency or "",
			"remarks": row.remarks or "",
			"side": "debit" if debit > credit else "credit",
		}
		for fieldname, info in dimension_payload.items():
			entry[f"dim:{fieldname}"] = info.get("title") or info.get("value") or ""
		rows.append(entry)

	sortable_fields = _gl_detail_sortable_fields(dimensions)
	rows = sort_rows(rows, spec, sortable_fields)
	paged = _paginate_gl_detail_rows(rows, spec)

	return {
		"voucher_header": _voucher_header(spec, paged["totals"]),
		"dimensions": [
			{
				"fieldname": dimension["fieldname"],
				"label": dimension["label"],
				"label_fa": dimension.get("label_fa"),
				"document_type": dimension.get("document_type"),
				"is_native": dimension.get("is_native", 0),
			}
			for dimension in dimensions
		],
		"gl_dimension_layout": gl_dimension_layout_mode(len(dimensions)),
		"gl_dimension_expand_threshold": GL_DIMENSION_EXPAND_THRESHOLD,
		**paged,
		"warnings": collect_scope_warnings(spec),
	}


def _row_dimensions(
	dimensions: list[dict],
	row: dict,
	dimension_titles: dict[str, dict[str, str]],
) -> dict[str, dict]:
	payload: dict[str, dict] = {}
	for dimension in dimensions:
		fieldname = dimension["fieldname"]
		value = row.get(fieldname) or ""
		title = dimension_titles.get(fieldname, {}).get(value, "") if value else ""
		payload[fieldname] = {
			"fieldname": fieldname,
			"label": dimension["label"],
			"label_fa": dimension.get("label_fa"),
			"value": value,
			"title": title or value,
		}
	return payload


def _gl_detail_sortable_fields(dimensions: list[dict]) -> frozenset[str]:
	# FUTURE ENHANCEMENT: expose dim:* sorting in the UI once QuerySpec validation accepts
	# dynamic dimension sort fields without changing DocumentScope or summary builders.
	return GL_GROUP_SORTABLE_FIELDS | frozenset(f"dim:{dimension['fieldname']}" for dimension in dimensions)


def _dimension_title_maps(dimensions: list[dict], raw_rows: list[dict]) -> dict[str, dict[str, str]]:
	maps: dict[str, dict[str, str]] = {}
	for dimension in dimensions:
		fieldname = dimension["fieldname"]
		values = {row.get(fieldname) for row in raw_rows if row.get(fieldname)}
		maps[fieldname] = _titles_for_dimension(fieldname, dimension.get("document_type"), values)
	return maps


def _titles_for_dimension(fieldname: str, document_type: str | None, values: set[str]) -> dict[str, str]:
	if not values:
		return {}
	value_list = list(values)
	if fieldname == "cost_center":
		return {
			row.name: row.cost_center_name or row.name
			for row in frappe.get_all(
				"Cost Center",
				filters={"name": ["in", value_list]},
				fields=["name", "cost_center_name"],
			)
		}
	if fieldname == "project":
		return {
			row.name: row.project_name or row.name
			for row in frappe.get_all(
				"Project",
				filters={"name": ["in", value_list]},
				fields=["name", "project_name"],
			)
		}
	if document_type and frappe.db.exists("DocType", document_type):
		meta = frappe.get_meta(document_type)
		title_field = meta.get_title_field() or "name"
		fields = ["name"]
		if title_field != "name":
			fields.append(title_field)
		return {
			row.name: (getattr(row, title_field, None) or row.name)
			for row in frappe.get_all(
				document_type,
				filters={"name": ["in", value_list]},
				fields=fields,
			)
		}
	return {value: value for value in value_list}


def _paginate_gl_detail_rows(rows: list[dict], spec: AccountExplorerQuerySpec) -> dict:
	total_debit = sum(flt(row.get("debit")) for row in rows)
	total_credit = sum(flt(row.get("credit")) for row in rows)
	page = spec.pagination.page
	page_size = spec.pagination.page_size
	offset = (page - 1) * page_size
	page_rows = rows[offset : offset + page_size]

	return {
		"rows": page_rows,
		"totals": {
			"debit": total_debit,
			"credit": total_credit,
		},
		"pagination": {
			"page": page,
			"page_size": page_size,
			"total_rows": len(rows),
			"has_next": offset + page_size < len(rows),
		},
	}


def _account_name_map(accounts: set[str]) -> dict[str, str]:
	if not accounts:
		return {}
	return {
		row.name: row.account_name
		for row in frappe.get_all(
			"Account",
			filters={"name": ["in", list(accounts)]},
			fields=["name", "account_name"],
		)
	}


def _voucher_header(spec: AccountExplorerQuerySpec, totals: dict | None = None) -> dict:
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
		"party_name": None,
		"voucher_title": spec.voucher_scope.voucher_no,
		"total_debit": flt((totals or {}).get("debit")),
		"total_credit": flt((totals or {}).get("credit")),
	}
	if row:
		header["posting_date"] = str(row[0].posting_date)
		header["party_type"] = row[0].party_type
		header["party"] = row[0].party
		header["party_name"] = _party_name(row[0].party_type, row[0].party)
	enrich_voucher_rows([header])
	return header
