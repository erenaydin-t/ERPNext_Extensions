# Copyright (c) 2026, ERPNext Extensions contributors
"""Backward-compatible re-exports (use domain/* or core/* in new code)."""

from __future__ import annotations

from erpnext_extensions.iran_accounting.domain.currency import (  # noqa: F401
	amount_is_fractional,
	cint_safe,
	get_company_currency,
	get_currency_precision,
	is_irr_company,
	is_irr_currency,
	is_zero_decimal_currency,
	round_currency,
	round_currency_amount,
	round_if_irr,
	round_row_amount,
)
from erpnext_extensions.iran_accounting.domain.ledger_rounding import (  # noqa: F401
	GL_AMOUNT_FIELDS,
	SLE_MONETARY_FIELDS,
	STOCK_ENTRY_ITEM_MONETARY_FIELDS,
	STOCK_ENTRY_TOTAL_FIELDS,
	reconcile_irr_sle_after_rounding,
	round_gl_entry_amounts,
	round_sle_monetary_fields,
	round_stock_entry_totals,
)
