# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

"""Exact DECIMAL(30,9) persistence for Facility Management Currency fields."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import frappe
from frappe.utils import cstr

FACILITY_INPUT_CURRENCY_FIELDS: tuple[str, ...] = (
	"principal_amount",
	"profit_amount",
	"opening_paid_principal_amount",
	"opening_paid_profit_amount",
	"opening_paid_penalty_amount",
)

FACILITY_REPAYMENT_CURRENCY_FIELDS: tuple[str, ...] = (
	"principal_amount",
	"profit_amount",
	"penalty_amount",
)


def parse_facility_amount(val: Any) -> Decimal:
	if val is None or val == "":
		return Decimal("0")
	if isinstance(val, Decimal):
		amount = val
	else:
		amount = Decimal(cstr(val).strip().replace(",", ""))
	return amount.quantize(Decimal("0.000000001"), rounding=ROUND_HALF_UP)


def persist_exact_currency_fields(doctype: str, name: str, fields: dict[str, Any]) -> None:
	if not name or not fields:
		return
	for fieldname, val in fields.items():
		if val is None:
			continue
		amount = parse_facility_amount(val)
		amount_str = format(amount, "f")
		frappe.db.sql(
			f"UPDATE `tab{doctype}` SET `{fieldname}` = %s WHERE name = %s",
			(amount_str, name),
		)


def get_exact_currency_char(doctype: str, name: str, fieldname: str) -> str:
	row = frappe.db.sql(
		f"SELECT CAST(`{fieldname}` AS CHAR) FROM `tab{doctype}` WHERE name = %s",
		(name,),
	)
	if not row or row[0][0] is None:
		return "0"
	return cstr(row[0][0]).strip()


def get_exact_currency_decimal(doctype: str, name: str, fieldname: str) -> Decimal:
	return parse_facility_amount(get_exact_currency_char(doctype, name, fieldname))
