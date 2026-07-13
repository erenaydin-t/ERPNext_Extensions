# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

from erpnext_extensions.iran_accounting.account_explorer.constants import CURRENCY_SORTABLE_FIELDS
from erpnext_extensions.iran_accounting.account_explorer.currency_opening import (
	get_currency_opening_balances,
	get_currency_period_balances,
)
from erpnext_extensions.iran_accounting.account_explorer.measures import measures_from_opening_period
from erpnext_extensions.iran_accounting.account_explorer.pagination import paginate_summary_rows, sort_rows
from erpnext_extensions.iran_accounting.account_explorer.schemas import AccountExplorerQuerySpec


def build_currency_summary(spec: AccountExplorerQuerySpec) -> dict:
	currency_type = spec.document_scope.currency.currency_type or "account_currency"
	opening = get_currency_opening_balances(spec, currency_type=currency_type)
	period = get_currency_period_balances(spec, currency_type=currency_type)
	keys = sorted(set(opening.keys()) | set(period.keys()), key=lambda item: (item == "", item))

	rows: list[dict] = []
	for currency in keys:
		if not currency:
			continue
		opening_debit, opening_credit = opening.get(currency, (0.0, 0.0))
		period_debit, period_credit = period.get(currency, (0.0, 0.0))
		measures = measures_from_opening_period(opening_debit, opening_credit, period_debit, period_credit)
		rows.append(
			{
				"row_key": f"currency:{currency}",
				"currency": currency,
				"display_code": currency,
				"display_title": currency,
				"is_virtual_group": 0,
				"drill_down_enabled": 1,
				**measures,
			}
		)

	rows = sort_rows(rows, spec, CURRENCY_SORTABLE_FIELDS)
	result = paginate_summary_rows(rows, spec)
	result["warnings"] = []
	result["currency_type"] = currency_type
	return result
