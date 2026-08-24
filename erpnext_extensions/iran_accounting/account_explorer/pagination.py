# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

from frappe.utils import flt

from erpnext_extensions.iran_accounting.account_explorer.constants import (
	VIRTUAL_DIMENSION_UNSPECIFIED_PREFIX,
	VIRTUAL_PARTY_UNSPECIFIED_KEY,
	VIRTUAL_UNIFIED_UNMAPPED_KEY,
)
from erpnext_extensions.iran_accounting.account_explorer.measures import (
	finalize_measures,
	row_has_activity,
	sum_measure_rows,
)
from erpnext_extensions.iran_accounting.account_explorer.schemas import AccountExplorerQuerySpec

# Empty-classification presentation markers (not Account Unclassified taxonomy).
_EMPTY_CLASSIFICATION_DISPLAY_CODES = frozenset({"__UNSPECIFIED__", "__UNMAPPED__", "-"})


def cstr_lower(value):
	return (value or "").casefold()


def is_empty_classification_value(value) -> bool:
	"""True for null / blank / whitespace-only classification keys."""
	if value is None:
		return True
	if isinstance(value, str) and value.strip() == "":
		return True
	return False


def is_empty_classification_presentation_row(row: dict | None) -> bool:
	"""True for empty / Unspecified / Unassigned / Unmapped classification buckets.

	Account-axis Unclassified (taxonomy) is intentionally not matched here.
	"""
	if not row:
		return False
	row_key = str(row.get("row_key") or "")
	if row_key == VIRTUAL_PARTY_UNSPECIFIED_KEY:
		return True
	if row_key == VIRTUAL_UNIFIED_UNMAPPED_KEY:
		return True
	if row_key.startswith(VIRTUAL_DIMENSION_UNSPECIFIED_PREFIX):
		return True
	display_code = str(row.get("display_code") or "")
	if display_code in _EMPTY_CLASSIFICATION_DISPLAY_CODES and row.get("is_virtual_group"):
		return True
	if "dimension_value" in row and is_empty_classification_value(row.get("dimension_value")):
		return True
	# Empty party / unified-party keys are excluded regardless of virtual markers.
	if "party" in row and is_empty_classification_value(row.get("party")):
		return True
	if "party_type" in row and is_empty_classification_value(row.get("party_type")) and "party" in row:
		return True
	if "unified_party" in row and is_empty_classification_value(row.get("unified_party")):
		return True
	if "currency" in row and is_empty_classification_value(row.get("currency")):
		return True
	return False


def exclude_empty_classification_rows(rows: list[dict]) -> list[dict]:
	"""Drop empty-classification buckets before totals / pagination."""
	return [row for row in rows if not is_empty_classification_presentation_row(row)]


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

	# v4.6.2: empty classification is excluded before aggregation/totals/pagination.
	rows = exclude_empty_classification_rows(rows)
	totals = sum_measure_rows(rows)

	total_rows = len(rows)
	page = spec.pagination.page
	page_size = spec.pagination.page_size
	offset = (page - 1) * page_size
	page_rows = rows[offset : offset + page_size]

	return {
		"rows": page_rows,
		"totals": totals,
		"pagination": {
			"page": page,
			"page_size": page_size,
			"total_rows": total_rows,
			"has_next": offset + page_size < total_rows,
		},
	}
