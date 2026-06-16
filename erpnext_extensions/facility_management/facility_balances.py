# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

from typing import Any

import frappe
from frappe.utils import flt, getdate


def _as_on_filter(as_on_date) -> tuple:
	if not as_on_date:
		return (None, None)
	d = getdate(as_on_date)
	return (d, d)


def get_repayment_sums(
	facility: str,
	*,
	as_on_date=None,
	exclude_names: list[str] | None = None,
) -> dict[str, float]:
	"""Sum submitted Facility Repayment amounts (source of truth for paid totals)."""
	as_on, _ = _as_on_filter(as_on_date)
	conditions = ["facility = %s", "docstatus = 1"]
	params: list[Any] = [facility]
	if as_on:
		conditions.append("posting_date <= %s")
		params.append(as_on)
	if exclude_names:
		conditions.append("name NOT IN ({})".format(", ".join(["%s"] * len(exclude_names))))
		params.extend(exclude_names)
	where = " AND ".join(conditions)
	row = frappe.db.sql(
		f"""
		SELECT
			COALESCE(SUM(principal_amount), 0) AS principal,
			COALESCE(SUM(profit_amount), 0) AS profit,
			COALESCE(SUM(penalty_amount), 0) AS penalty
		FROM `tabFacility Repayment`
		WHERE {where}
		""",
		tuple(params),
		as_dict=True,
	)
	r = row[0] if row else {}
	return {
		"repaid_principal": flt(r.get("principal")),
		"repaid_profit": flt(r.get("profit")),
		"repaid_penalty": flt(r.get("penalty")),
	}


def get_facility_balance_row(doc, *, as_on_date=None) -> dict[str, Any]:
	"""Paid / remaining from opening fields + submitted repayments (not from GL)."""
	fac = doc if hasattr(doc, "get") else frappe.get_doc("Facility", doc)
	rep = get_repayment_sums(fac.name, as_on_date=as_on_date)
	paid_principal = flt(fac.opening_paid_principal_amount) + rep["repaid_principal"]
	paid_profit = flt(fac.opening_paid_profit_amount) + rep["repaid_profit"]
	paid_penalty = flt(fac.opening_paid_penalty_amount) + rep["repaid_penalty"]
	principal = flt(fac.principal_amount)
	profit = flt(fac.profit_amount)
	remaining_principal = principal - paid_principal
	remaining_profit = profit - paid_profit
	return {
		"facility": fac.name,
		"facility_name": fac.facility_name,
		"facility_type": getattr(fac, "facility_type", None),
		"bank": fac.bank,
		"company": fac.company,
		"status": fac.status,
		"principal_amount": principal,
		"profit_amount": profit,
		"total_liability_amount": flt(fac.total_liability_amount) or (principal + profit),
		"paid_principal": paid_principal,
		"paid_profit": paid_profit,
		"paid_penalty": paid_penalty,
		"remaining_principal": remaining_principal,
		"remaining_profit": remaining_profit,
		"remaining_total": remaining_principal + remaining_profit,
		"receipt_journal_entry": fac.receipt_journal_entry,
		"is_opening_facility": cint(fac.is_opening_facility),
	}


def cint(v):
	from frappe.utils import cint as _cint

	return _cint(v)
