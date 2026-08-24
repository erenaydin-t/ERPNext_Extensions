# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

import frappe

from erpnext_extensions.iran_accounting.account_explorer.constants import CURRENCY_SORTABLE_FIELDS
from erpnext_extensions.iran_accounting.account_explorer.currency_opening import (
	get_currency_company_opening_balances,
	get_currency_company_period_balances,
	get_currency_opening_balances,
	get_currency_period_balances,
)
from erpnext_extensions.iran_accounting.account_explorer.measures import (
	measures_from_opening_period,
	sum_measure_rows,
)
from erpnext_extensions.iran_accounting.account_explorer.pagination import paginate_summary_rows, sort_rows
from erpnext_extensions.iran_accounting.account_explorer.schemas import AccountExplorerQuerySpec

COMPANY_MEASURE_PREFIX = "company_"
COMPANY_MEASURE_FIELDS = (
	"opening_debit",
	"opening_credit",
	"period_debit",
	"period_credit",
	"closing_debit",
	"closing_credit",
	"net_balance",
	"debit_balance",
	"credit_balance",
)


def build_currency_columns(company_currency: str | None = None) -> list[dict]:
	"""Currency-axis grid columns: native amounts + company-currency equivalents."""
	cc = company_currency or "Company"
	return [
		{"id": "currency", "label": "Currency", "fieldtype": "Data", "width": 100},
		{"id": "period_debit", "label": "Debit Amount (Currency)", "fieldtype": "Currency", "width": 160},
		{
			"id": "company_period_debit",
			"label": f"Debit Amount ({cc})",
			"fieldtype": "Currency",
			"width": 160,
		},
		{"id": "period_credit", "label": "Credit Amount (Currency)", "fieldtype": "Currency", "width": 160},
		{
			"id": "company_period_credit",
			"label": f"Credit Amount ({cc})",
			"fieldtype": "Currency",
			"width": 160,
		},
		{"id": "net_balance", "label": "Balance (Currency)", "fieldtype": "Currency", "width": 160},
		{
			"id": "company_net_balance",
			"label": f"Balance ({cc})",
			"fieldtype": "Currency",
			"width": 160,
		},
	]


def build_currency_summary(spec: AccountExplorerQuerySpec) -> dict:
	currency_type = spec.document_scope.currency.currency_type or "account_currency"
	opening = get_currency_opening_balances(spec, currency_type=currency_type)
	period = get_currency_period_balances(spec, currency_type=currency_type)
	company_opening = get_currency_company_opening_balances(spec, currency_type=currency_type)
	company_period = get_currency_company_period_balances(spec, currency_type=currency_type)
	keys = sorted(
		set(opening.keys()) | set(period.keys()) | set(company_opening.keys()) | set(company_period.keys()),
		key=lambda item: (item == "", item),
	)

	rows: list[dict] = []
	for currency in keys:
		if not currency:
			continue
		opening_debit, opening_credit = opening.get(currency, (0.0, 0.0))
		period_debit, period_credit = period.get(currency, (0.0, 0.0))
		measures = measures_from_opening_period(opening_debit, opening_credit, period_debit, period_credit)

		c_opening_debit, c_opening_credit = company_opening.get(currency, (0.0, 0.0))
		c_period_debit, c_period_credit = company_period.get(currency, (0.0, 0.0))
		company_measures = measures_from_opening_period(
			c_opening_debit, c_opening_credit, c_period_debit, c_period_credit
		)

		row = {
			"row_key": f"currency:{currency}",
			"currency": currency,
			"display_code": currency,
			"display_title": currency,
			"is_virtual_group": 0,
			"drill_down_enabled": 1,
			**measures,
		}
		for field in COMPANY_MEASURE_FIELDS:
			row[f"{COMPANY_MEASURE_PREFIX}{field}"] = company_measures.get(field) or 0.0
		rows.append(row)

	rows = sort_rows(rows, spec, CURRENCY_SORTABLE_FIELDS)
	result = paginate_summary_rows(rows, spec)

	# Totals must never sum mixed native currencies — only company currency.
	from erpnext_extensions.iran_accounting.account_explorer.measures import row_has_activity

	totals_source = rows
	if spec.hide_zero_rows:
		totals_source = [row for row in rows if row_has_activity(row)]
	result["totals"] = sum_measure_rows(
		[
			{field: row.get(f"{COMPANY_MEASURE_PREFIX}{field}") or 0.0 for field in COMPANY_MEASURE_FIELDS}
			for row in totals_source
		]
	)
	result["warnings"] = []
	result["currency_type"] = currency_type
	company_currency = frappe.get_cached_value("Company", spec.company, "default_currency")
	result["totals_currency"] = company_currency
	return result
