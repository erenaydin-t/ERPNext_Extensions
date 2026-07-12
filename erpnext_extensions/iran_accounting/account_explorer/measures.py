# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

from frappe.utils import flt

from erpnext_extensions.iran_accounting.account_explorer.constants import MEASURE_FIELDS


def zero_measures() -> dict[str, float]:
	return {field: 0.0 for field in MEASURE_FIELDS}


def add_measures(target: dict, source: dict) -> None:
	for field in MEASURE_FIELDS:
		target[field] = flt(target.get(field)) + flt(source.get(field))


def finalize_measures(row: dict) -> dict:
	opening_net = flt(row.get("opening_debit")) - flt(row.get("opening_credit"))
	period_net = flt(row.get("period_debit")) - flt(row.get("period_credit"))
	closing_net = opening_net + period_net
	row["net_balance"] = closing_net
	row["closing_debit"] = max(closing_net, 0)
	row["closing_credit"] = abs(min(closing_net, 0))
	row["debit_balance"] = row["closing_debit"]
	row["credit_balance"] = row["closing_credit"]
	return row


def measures_from_opening_period(
	opening_debit: float, opening_credit: float, period_debit: float, period_credit: float
) -> dict:
	row = {
		"opening_debit": flt(opening_debit),
		"opening_credit": flt(opening_credit),
		"period_debit": flt(period_debit),
		"period_credit": flt(period_credit),
		"closing_debit": 0.0,
		"closing_credit": 0.0,
		"net_balance": 0.0,
		"debit_balance": 0.0,
		"credit_balance": 0.0,
	}
	return finalize_measures(row)


def row_has_activity(row: dict) -> bool:
	for field in MEASURE_FIELDS:
		if flt(row.get(field)):
			return True
	return False


def sum_measure_rows(rows: list[dict]) -> dict:
	total = zero_measures()
	for row in rows:
		add_measures(total, row)
	return finalize_measures(total)
