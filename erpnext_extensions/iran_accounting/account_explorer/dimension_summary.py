# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

from erpnext_extensions.iran_accounting.account_explorer.constants import DIMENSION_SORTABLE_FIELDS
from erpnext_extensions.iran_accounting.account_explorer.dimension_discovery import (
	get_dimension_display_title,
	validate_dimension_field,
)
from erpnext_extensions.iran_accounting.account_explorer.dimension_opening import (
	get_dimension_opening_balances,
	get_dimension_period_balances,
)
from erpnext_extensions.iran_accounting.account_explorer.measures import measures_from_opening_period
from erpnext_extensions.iran_accounting.account_explorer.pagination import (
	is_empty_classification_value,
	paginate_summary_rows,
	sort_rows,
)
from erpnext_extensions.iran_accounting.account_explorer.schemas import AccountExplorerQuerySpec


def build_dimension_summary(spec: AccountExplorerQuerySpec) -> dict:
	dimension_type = spec.dimension_scope.dimension_type
	validate_dimension_field(dimension_type)

	opening = get_dimension_opening_balances(spec, dimension_type)
	period = get_dimension_period_balances(spec, dimension_type)
	keys = set(opening.keys()) | set(period.keys())

	rows: list[dict] = []
	for value in sorted(keys, key=lambda item: (item == "", item)):
		# v4.6.2: empty / unassigned dimension values are excluded before aggregation.
		if is_empty_classification_value(value):
			continue
		opening_debit, opening_credit = opening.get(value, (0.0, 0.0))
		period_debit, period_credit = period.get(value, (0.0, 0.0))
		rows.append(
			{
				"row_key": f"dimension:{dimension_type}:{value}",
				"dimension_type": dimension_type,
				"dimension_value": value,
				"display_code": value,
				"display_title": get_dimension_display_title(dimension_type, value),
				"is_virtual_group": 0,
				"drill_down_enabled": 1,
				**measures_from_opening_period(
					opening_debit, opening_credit, period_debit, period_credit
				),
			}
		)

	rows = sort_rows(rows, spec, DIMENSION_SORTABLE_FIELDS)
	result = paginate_summary_rows(rows, spec)
	result["warnings"] = []
	result["dimension_type"] = dimension_type
	return result
