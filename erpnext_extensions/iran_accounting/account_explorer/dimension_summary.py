# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

from erpnext_extensions.iran_accounting.account_explorer.constants import (
	DIMENSION_SORTABLE_FIELDS,
	VIRTUAL_DIMENSION_UNSPECIFIED_PREFIX,
)
from erpnext_extensions.iran_accounting.account_explorer.dimension_discovery import (
	get_dimension_display_title,
	not_specified_label,
	validate_dimension_field,
)
from erpnext_extensions.iran_accounting.account_explorer.dimension_opening import (
	get_dimension_opening_balances,
	get_dimension_period_balances,
)
from erpnext_extensions.iran_accounting.account_explorer.measures import measures_from_opening_period
from erpnext_extensions.iran_accounting.account_explorer.pagination import paginate_summary_rows, sort_rows
from erpnext_extensions.iran_accounting.account_explorer.schemas import AccountExplorerQuerySpec


def build_dimension_summary(spec: AccountExplorerQuerySpec) -> dict:
	dimension_field = spec.dimension_scope.dimension_field
	validate_dimension_field(dimension_field)

	opening = get_dimension_opening_balances(spec, dimension_field)
	period = get_dimension_period_balances(spec, dimension_field)
	keys = set(opening.keys()) | set(period.keys())

	rows: list[dict] = []
	for value in sorted(keys, key=lambda item: (item == "", item)):
		opening_debit, opening_credit = opening.get(value, (0.0, 0.0))
		period_debit, period_credit = period.get(value, (0.0, 0.0))
		is_unspecified = value == ""
		display_code = "__NOT_SPECIFIED__" if is_unspecified else value
		display_title = not_specified_label() if is_unspecified else get_dimension_display_title(
			dimension_field, value
		)
		row_key = (
			f"{VIRTUAL_DIMENSION_UNSPECIFIED_PREFIX}:{dimension_field}"
			if is_unspecified
			else f"dimension:{dimension_field}:{value}"
		)
		rows.append(
			{
				"row_key": row_key,
				"dimension_field": dimension_field,
				"dimension_value": value,
				"display_code": display_code,
				"display_title": display_title,
				"is_virtual_group": 1 if is_unspecified else 0,
				"drill_down_enabled": 0 if is_unspecified else 1,
				**measures_from_opening_period(
					opening_debit, opening_credit, period_debit, period_credit
				),
			}
		)

	rows = sort_rows(rows, spec, DIMENSION_SORTABLE_FIELDS)
	result = paginate_summary_rows(rows, spec)
	result["warnings"] = []
	result["dimension_field"] = dimension_field
	return result
