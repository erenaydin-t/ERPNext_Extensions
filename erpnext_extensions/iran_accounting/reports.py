# Copyright (c) 2026, ERPNext Extensions contributors

from __future__ import annotations

import frappe

from erpnext_extensions.iran_accounting.rounding import get_company_currency, is_irr_company, round_currency
from erpnext_extensions.iran_accounting.stock_ledger_report import (
	STOCK_LEDGER_MONETARY_FIELDNAMES,
	monetary_fieldnames_from_columns,
	sanitize_stock_ledger_report,
)


def sanitize_gl_report_row(row, company):
	if not is_irr_company(company):
		return row
	currency = get_company_currency(company)
	for field in ("debit", "credit", "balance"):
		if field in row and row[field] not in (None, ""):
			row[field] = round_currency(row[field], currency)
	return row


def sanitize_stock_ledger_row(row, company, monetary_fields=None):
	from erpnext_extensions.iran_accounting.stock_ledger_report import sanitize_stock_ledger_row as _sanitize

	return _sanitize(row, company, monetary_fields)


def sanitize_statement_row(row, company):
	if not is_irr_company(company):
		return row
	currency = get_company_currency(company)
	for field in ("debit", "credit", "balance"):
		if field in row and row[field] not in (None, ""):
			row[field] = round_currency(row[field], currency)
	return row


def run_general_ledger_report(filters: dict):
	from erpnext.accounts.report.general_ledger.general_ledger import execute

	filters = frappe._dict(filters)
	columns, data = execute(filters)
	company = filters.get("company")
	if company and is_irr_company(company):
		for row in data:
			sanitize_gl_report_row(row, company)
	return columns, data


def run_stock_ledger_report(filters: dict):
	from erpnext.stock.report.stock_ledger.stock_ledger import execute

	filters = frappe._dict(filters)
	columns, data = execute(filters)
	company = filters.get("company")
	if company and is_irr_company(company):
		columns, data = sanitize_stock_ledger_report(columns, data, company, filters)
	return columns, data


def stock_ledger_report_monetary_fields(columns, filters=None):
	filters = frappe._dict(filters or {})
	vft = filters.get("valuation_field_type") or "Currency"
	return monetary_fieldnames_from_columns(columns, vft) or list(STOCK_LEDGER_MONETARY_FIELDNAMES)


def run_statement_of_accounts_report(filters: dict):
	from erpnext.accounts.report.general_ledger.general_ledger import execute

	return execute(filters)
