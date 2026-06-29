# Copyright (c) 2026, ERPNext Extensions contributors
"""Stock Ledger report IRR monetary sanitization and validation helpers."""

from __future__ import annotations

import re
from typing import Any

import frappe
from frappe.utils import cstr, flt

from erpnext_extensions.iran_accounting.rounding import (
	amount_is_fractional,
	get_company_currency,
	is_irr_company,
	round_currency,
)

# Report-only quantity columns (not all exist on tabStock Ledger Entry).
STOCK_LEDGER_QUANTITY_FIELDNAMES = (
	"in_qty",
	"out_qty",
	"qty_after_transaction",
	"actual_qty",
)

STOCK_LEDGER_MONETARY_FIELDNAMES = (
	"incoming_rate",
	"valuation_rate",
	"in_out_rate",
	"stock_value",
	"stock_value_difference",
)

SLE_DB_QUANTITY_FIELDS = ("actual_qty", "qty_after_transaction")

# SLE DB: integer monetary amounts (IRR).
SLE_DB_VALUE_FIELDS = ("stock_value", "stock_value_difference")

# SLE DB rates — strict integer for IRR (same as monetary amounts).
SLE_DB_RATE_FIELDS = ("incoming_rate", "valuation_rate")

MONETARY_COLUMN_LABEL_KEYWORDS = (
	"incoming rate",
	"outgoing rate",
	"avg rate",
	"valuation rate",
	"balance value",
	"value change",
	"stock value",
	"incoming value",
	"outgoing value",
	"amount",
	"basic amount",
	"debit",
	"credit",
	"balance",
)

QUANTITY_COLUMN_LABEL_KEYWORDS = (
	"in qty",
	"out qty",
	"balance qty",
	"actual qty",
	"qty after",
	"transfer qty",
	"qty",
)


def _label_key(label: str) -> str:
	return (label or "").strip().lower()


def is_stock_ledger_monetary_column(col: dict, valuation_field_type: str = "Currency") -> bool:
	fieldname = col.get("fieldname") or ""
	fieldtype = col.get("fieldtype") or ""
	label = _label_key(col.get("label") or col.get("fieldname") or "")
	if fieldname in STOCK_LEDGER_QUANTITY_FIELDNAMES:
		return False
	if fieldname in STOCK_LEDGER_MONETARY_FIELDNAMES:
		return True
	if any(k in label for k in QUANTITY_COLUMN_LABEL_KEYWORDS):
		if "rate" not in label and "value" not in label and "amount" not in label:
			return False
	if any(k in label for k in MONETARY_COLUMN_LABEL_KEYWORDS):
		return True
	if fieldtype == "Currency":
		return True
	if fieldtype in ("Float", "Rate") and col.get("convertible") in ("rate", "currency"):
		return valuation_field_type == "Currency"
	return False


def monetary_fieldnames_from_columns(columns: list[dict], valuation_field_type: str = "Currency") -> list[str]:
	out: list[str] = []
	for col in columns or []:
		fn = col.get("fieldname")
		if not fn:
			continue
		if is_stock_ledger_monetary_column(col, valuation_field_type):
			out.append(fn)
	return list(dict.fromkeys(out))


def quantity_fieldnames_from_columns(columns: list[dict]) -> list[str]:
	out: list[str] = []
	for col in columns or []:
		fn = col.get("fieldname")
		if not fn:
			continue
		label = _label_key(col.get("label") or "")
		if fn in STOCK_LEDGER_QUANTITY_FIELDNAMES:
			out.append(fn)
		elif any(k in label for k in QUANTITY_COLUMN_LABEL_KEYWORDS):
			out.append(fn)
	return list(dict.fromkeys(out))


def sanitize_stock_ledger_row(
	row: dict,
	company: str,
	monetary_fields: tuple[str, ...] | None = None,
) -> dict:
	if not is_irr_company(company) or not isinstance(row, dict):
		return row
	if row.get("item_code") == "'Total'":
		return row
	currency = get_company_currency(company)
	fields = monetary_fields or STOCK_LEDGER_MONETARY_FIELDNAMES
	for field in fields:
		if field in row and row[field] not in (None, ""):
			row[field] = round_currency(row[field], currency)
	return row


def sanitize_stock_ledger_report(columns: list, data: list, company: str, filters: dict | None = None) -> tuple[list, list]:
	if not company or not is_irr_company(company):
		return columns, data
	valuation_field_type = (filters or {}).get("valuation_field_type") or "Currency"
	monetary = tuple(monetary_fieldnames_from_columns(columns, valuation_field_type))
	for row in data or []:
		if isinstance(row, dict):
			sanitize_stock_ledger_row(row, company, monetary)
			_align_stock_reconciliation_report_row(row)
	return columns, data


def _align_stock_reconciliation_report_row(row: dict) -> None:
	"""Desk report leaves in_qty/out_qty zero for some opening Stock Reconciliation rows (non-batch)."""
	if row.get("voucher_type") != "Stock Reconciliation":
		return

	in_qty = flt(row.get("in_qty"))
	out_qty = flt(row.get("out_qty"))
	qty_after = flt(row.get("qty_after_transaction"))
	value_change = flt(row.get("stock_value_difference"))
	val_rate = flt(row.get("valuation_rate"))

	# Non-batch SR rows often have actual_qty=0; core may leave in_qty/out_qty unset (e.g. voucher-only filter).
	if not in_qty and not out_qty:
		if value_change > 0 and qty_after > 0:
			row["in_qty"] = qty_after
			row["out_qty"] = 0
			if not flt(row.get("incoming_rate")) and val_rate:
				row["incoming_rate"] = val_rate
			row["in_out_rate"] = 0
			return
		if value_change < 0:
			rate = val_rate or flt(row.get("incoming_rate"))
			if rate:
				row["out_qty"] = flt(value_change) / rate
			row["in_qty"] = 0
			row["incoming_rate"] = 0
			if rate and not flt(row.get("in_out_rate")):
				row["in_out_rate"] = rate
			return

	# Positive stock added (in only): never copy avg rate into Outgoing Rate (in_out_rate).
	if in_qty > 0 and out_qty >= 0:
		if not flt(row.get("incoming_rate")) and flt(row.get("valuation_rate")):
			row["incoming_rate"] = row.get("valuation_rate")
		if not out_qty:
			row["in_out_rate"] = 0


def fractional_cells_in_report_rows(
	rows: list[dict],
	company: str,
	monetary_fields: tuple[str, ...],
) -> list[dict]:
	if not is_irr_company(company):
		return []
	currency = get_company_currency(company)
	out = []
	for i, row in enumerate(rows or []):
		if not isinstance(row, dict) or row.get("item_code") == "'Total'":
			continue
		for field in monetary_fields:
			val = row.get(field)
			if val in (None, ""):
				continue
			if isinstance(val, str) and re.search(r"\.\d", val.replace(",", "")):
				out.append({"row_index": i, "field": field, "value": val, "reason": "decimal_string"})
			elif amount_is_fractional(val, currency):
				out.append({"row_index": i, "field": field, "value": val, "reason": "fractional_numeric"})
	return out


def default_stock_ledger_filters(
	company: str,
	voucher_no: str | None = None,
	from_date: str | None = None,
	to_date: str | None = None,
) -> dict:
	from frappe.utils import today

	from_date = from_date or today()
	to_date = to_date or today()
	filters = {
		"company": company,
		"from_date": from_date,
		"to_date": to_date,
		"valuation_field_type": "Currency",
	}
	if voucher_no:
		filters["voucher_no"] = voucher_no
	return filters


def run_stock_ledger_report_raw(filters: dict):
	from erpnext.stock.report.stock_ledger.stock_ledger import execute

	return execute(frappe._dict(filters))


def export_stock_ledger_xlsx_rows(filters: dict) -> tuple[list[dict], list[list[Any]]]:
	"""Same path as Desk export (query_report.run + build_xlsx_data)."""
	from frappe.desk.query_report import build_xlsx_data, format_fields, run as query_report_run

	filters = frappe.parse_json(filters) if isinstance(filters, str) else frappe._dict(filters)
	report_data = frappe._dict(
		query_report_run(
			"Stock Ledger",
			filters,
			are_default_filters=False,
		)
	)
	format_fields(report_data)
	xlsx_data, _widths, _styles = build_xlsx_data(
		report_data,
		include_indentation=0,
		include_filters=0,
		include_hidden_columns=0,
		build_styles=False,
	)
	return report_data.columns or [], xlsx_data


def fractional_monetary_in_xlsx(
	columns: list[dict],
	xlsx_rows: list[list[Any]],
	company: str,
) -> list[dict]:
	if not is_irr_company(company):
		return []
	currency = get_company_currency(company)
	if not xlsx_rows:
		return []
	header = [cstr(c).strip() for c in xlsx_rows[0]]
	col_meta = {(_label_key(c.get("label") or "")): c for c in columns or []}
	monetary_col_idx: list[tuple[int, str]] = []
	for idx, title in enumerate(header):
		label = _label_key(title)
		col = col_meta.get(label)
		if col and is_stock_ledger_monetary_column(col):
			monetary_col_idx.append((idx, title))
		elif any(k in label for k in MONETARY_COLUMN_LABEL_KEYWORDS) and not any(
			k in label for k in QUANTITY_COLUMN_LABEL_KEYWORDS
		):
			monetary_col_idx.append((idx, title))

	out = []
	for row_i, row in enumerate(xlsx_rows[1:], start=1):
		for col_i, title in monetary_col_idx:
			if col_i >= len(row):
				continue
			val = row[col_i]
			if val in (None, ""):
				continue
			s = cstr(val).strip()
			if re.search(r"\.\d", s.replace(",", "")):
				out.append({"row": row_i, "column": title, "value": s, "reason": "decimal_in_export"})
			elif isinstance(val, (int, float)) and amount_is_fractional(val, currency):
				out.append({"row": row_i, "column": title, "value": val, "reason": "fractional_in_export"})
	return out


def sle_db_snapshot(voucher_type: str, voucher_no: str) -> list[dict]:
	fields = (
		list(SLE_DB_VALUE_FIELDS)
		+ list(SLE_DB_RATE_FIELDS)
		+ list(SLE_DB_QUANTITY_FIELDS)
		+ ["name", "item_code", "warehouse"]
	)
	fields = list(dict.fromkeys(fields))
	return frappe.get_all(
		"Stock Ledger Entry",
		filters={"voucher_type": voucher_type, "voucher_no": voucher_no, "is_cancelled": 0},
		fields=fields,
		order_by="creation asc",
	)


def sle_db_fractional_values(company: str, sle_rows: list[dict]) -> dict[str, list]:
	currency = get_company_currency(company)
	value_hits = []
	rate_hits = []
	all_monetary = SLE_DB_VALUE_FIELDS + SLE_DB_RATE_FIELDS
	for row in sle_rows:
		for field in all_monetary:
			val = row.get(field)
			if val not in (None, "") and amount_is_fractional(val, currency):
				hit = {"sle": row.get("name"), "field": field, "value": val}
				if field in SLE_DB_RATE_FIELDS:
					rate_hits.append(hit)
				else:
					value_hits.append(hit)
	return {"value_fields": value_hits, "rate_fields": rate_hits}
