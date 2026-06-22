# Copyright (c) 2026, ERPNext Extensions contributors

from __future__ import annotations

from erpnext_extensions.iran_accounting.rounding import is_irr_company, round_sle_monetary_fields


def validate_stock_ledger_entry(doc, method=None):
	if not doc.company or not is_irr_company(doc.company):
		return
	round_sle_monetary_fields(doc, doc.company)


def before_insert_stock_ledger_entry(doc, method=None):
	validate_stock_ledger_entry(doc, method)
