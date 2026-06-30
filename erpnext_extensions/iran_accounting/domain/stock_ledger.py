# Copyright (c) 2026, ERPNext Extensions contributors

from __future__ import annotations

import frappe

from erpnext_extensions.iran_accounting.domain.currency import is_irr_company
from erpnext_extensions.iran_accounting.domain.ledger_rounding import round_sle_monetary_fields
from erpnext_extensions.iran_accounting.domain.stock_reconciliation_sync import (
	sync_irr_sle_from_stock_reconciliation_row,
)


def validate_stock_ledger_entry(doc, method=None):
	from erpnext_extensions.iran_accounting.integration.bootstrap import apply

	apply()
	if not doc.company or not is_irr_company(doc.company):
		return
	sync_irr_sle_from_stock_reconciliation_row(doc)
	round_sle_monetary_fields(doc, doc.company)


def before_insert_stock_ledger_entry(doc, method=None):
	validate_stock_ledger_entry(doc, method)
