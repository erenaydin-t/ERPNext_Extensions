# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT
"""Shared Facility Management DECIMAL(30,9) field lists.

Keep this as an explicit allowlist. Do not widen future Currency fields implicitly.
"""

from __future__ import annotations

TARGET_PRECISION = 30
TARGET_SCALE = 9
TARGET_LENGTH = 30

FACILITY_AMOUNT_DOCTYPES: tuple[str, ...] = ("Facility", "Facility Repayment")

TABLES_AND_COLUMNS: dict[str, list[str]] = {
	"tabFacility": [
		"principal_amount",
		"profit_amount",
		"total_liability_amount",
		"opening_paid_principal_amount",
		"opening_paid_profit_amount",
		"opening_paid_penalty_amount",
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
	],
}


def all_facility_currency_fieldnames() -> dict[str, list[str]]:
	return {
		"Facility": list(TABLES_AND_COLUMNS["tabFacility"]),
		"Facility Repayment": list(TABLES_AND_COLUMNS["tabFacility Repayment"]),
	}
