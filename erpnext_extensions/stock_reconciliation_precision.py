# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT
"""Discover Stock Reconciliation parent/child numeric fields for DECIMAL(30,9) patches."""

from __future__ import annotations

import frappe

PARENT_DOCTYPE = "Stock Reconciliation"

TARGET_PRECISION = 30
TARGET_SCALE = 9
TARGET_LENGTH = 30

NUMERIC_FIELDTYPES = frozenset({"Currency", "Float", "Percent"})

_FIELD_KEYWORDS = (
	"amount",
	"rate",
	"value",
	"valuation",
	"difference",
	"debit",
	"credit",
	"total",
	"price",
	"cost",
	"tax",
	"qty",
	"quantity",
	"conversion",
	"stock",
	"incoming",
	"outgoing",
)

FORCE_INCLUDE_FIELDNAMES = frozenset(
	{
		"difference_amount",
		"valuation_rate",
		"current_valuation_rate",
		"current_amount",
		"amount",
		"qty",
		"current_qty",
		"amount_difference",
	}
)


def stock_reconciliation_doctypes() -> list[str]:
	"""Parent doctype plus child doctypes from Table fields."""
	if not frappe.db.exists("DocType", PARENT_DOCTYPE):
		return []

	meta = frappe.get_meta(PARENT_DOCTYPE, cached=False)
	doctypes = [PARENT_DOCTYPE]
	for df in meta.fields:
		if df.fieldtype == "Table" and df.options:
			doctypes.append(df.options)
	return doctypes


def _field_matches(df) -> bool:
	if df.fieldname in FORCE_INCLUDE_FIELDNAMES:
		return df.fieldtype in NUMERIC_FIELDTYPES
	if df.fieldtype not in NUMERIC_FIELDTYPES:
		return False
	haystack = f"{df.fieldname or ''} {df.label or ''}".lower()
	return any(keyword in haystack for keyword in _FIELD_KEYWORDS)


def numeric_fields_for_doctype(doctype: str) -> list[str]:
	if not frappe.db.exists("DocType", doctype):
		return []
	meta = frappe.get_meta(doctype, cached=False)
	selected: set[str] = set()
	for df in meta.fields:
		if df.fieldname in FORCE_INCLUDE_FIELDNAMES and df.fieldtype not in NUMERIC_FIELDTYPES:
			continue
		if _field_matches(df):
			selected.add(df.fieldname)
	return sorted(selected)


def stock_reconciliation_tables_and_columns() -> dict[str, list[str]]:
	"""Map SQL table name -> column names to widen."""
	from frappe.utils import get_table_name

	tables: dict[str, list[str]] = {}
	for doctype in stock_reconciliation_doctypes():
		if not frappe.db.table_exists(doctype):
			continue
		table = get_table_name(doctype)
		cols = numeric_fields_for_doctype(doctype)
		if cols:
			tables[table] = cols
	return tables
