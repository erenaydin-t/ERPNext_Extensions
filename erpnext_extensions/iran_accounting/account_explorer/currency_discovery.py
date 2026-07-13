# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

import frappe


def discover_company_currencies(company: str) -> list[str]:
	if not company:
		return []
	rows = frappe.db.sql(
		"""
		select distinct account_currency as currency
		from `tabGL Entry`
		where company = %s and ifnull(account_currency, '') != '' and is_cancelled = 0
		union
		select distinct transaction_currency as currency
		from `tabGL Entry`
		where company = %s and ifnull(transaction_currency, '') != '' and is_cancelled = 0
		order by currency
		""",
		(company, company),
	)
	return [row[0] for row in rows if row[0]]
