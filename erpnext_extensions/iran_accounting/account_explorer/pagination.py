# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

from frappe.utils import flt

from erpnext_extensions.iran_accounting.account_explorer.measures import (
	finalize_measures,
	row_has_activity,
	sum_measure_rows,
)
from erpnext_extensions.iran_accounting.account_explorer.schemas import AccountExplorerQuerySpec


def cstr_lower(value):
	return (value or "").casefold()


def sort_rows(rows: list[dict], spec: AccountExplorerQuerySpec, sortable_fields) -> list:
	field = spec.pagination.sort_field
	if field not in sortable_fields:
		field = "display_code"
	reverse = spec.pagination.sort_order == "desc"

	def sort_key(row):
		value = row.get(field)
		if isinstance(value, int | float):
			return (0, flt(value))
		return (1, cstr_lower(value))

	return sorted(rows, key=sort_key, reverse=reverse)


def paginate_summary_rows(rows: list[dict], spec: AccountExplorerQuerySpec) -> dict:
	for row in rows:
		finalize_measures(row)

	if spec.hide_zero_rows:
		rows = [row for row in rows if row_has_activity(row)]

	total_rows = len(rows)
	page = spec.pagination.page
	page_size = spec.pagination.page_size
	offset = (page - 1) * page_size
	page_rows = rows[offset : offset + page_size]

	return {
		"rows": page_rows,
		"totals": sum_measure_rows(rows),
		"pagination": {
			"page": page,
			"page_size": page_size,
			"total_rows": total_rows,
			"has_next": offset + page_size < total_rows,
		},
	}
