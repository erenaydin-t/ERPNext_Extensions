# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT
"""Shared Facility Management DECIMAL(30,9) field lists."""

from __future__ import annotations

TARGET_PRECISION = 30
TARGET_SCALE = 9
TARGET_LENGTH = 30

FACILITY_AMOUNT_DOCTYPES: tuple[str, ...] = (
	"Facility",
	"Facility Repayment",
	"Facility Repayment Schedule",
)

# Authoritative column list (includes fields present on DocTypes + future names from spec).
TABLES_AND_COLUMNS: dict[str, list[str]] = {
	"tabFacility": [
		"principal_amount",
		"profit_amount",
		"total_liability_amount",
		"installment_amount",
		"opening_paid_principal_amount",
		"opening_paid_profit_amount",
		"opening_paid_penalty_amount",
		"opening_remaining_principal_amount",
		"opening_remaining_profit_amount",
		"received_amount",
		"paid_principal_amount",
		"paid_profit_amount",
		"paid_penalty_amount",
		"remaining_principal_amount",
		"remaining_profit_amount",
		"remaining_total_amount",
	],
	"tabFacility Repayment": [
		"principal_amount",
		"profit_amount",
		"penalty_amount",
		"total_payment_amount",
		"total_amount",
	],
	"tabFacility Repayment Schedule": [
		"installment_amount",
		"principal_amount",
		"profit_amount",
		"remaining_amount",
	],
}


def currency_fieldnames_for_doctype(doctype: str) -> list[str]:
	import frappe

	if not frappe.db.exists("DocType", doctype):
		return []
	meta = frappe.get_meta(doctype, cached=False)
	return [df.fieldname for df in meta.fields if df.fieldtype == "Currency"]


def all_facility_currency_fieldnames() -> dict[str, list[str]]:
	out: dict[str, list[str]] = {}
	for dt in FACILITY_AMOUNT_DOCTYPES:
		names = set(currency_fieldnames_for_doctype(dt))
		table = f"tab{dt}"
		for col in TABLES_AND_COLUMNS.get(table, []):
			names.add(col)
		out[dt] = sorted(names)
	return out
