# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT
"""Widen PDC accounting path columns to DECIMAL(30,9), including Payment Ledger Entry.

Idempotent. Complements expand_currency_precision* and expand_cheque_guarantee_amount_precision.
"""

from __future__ import annotations

from erpnext_extensions.cheque_management.pdc_accounting_precision import (
	expand_pdc_accounting_ledger_amount_precision,
)


def execute() -> None:
	expand_pdc_accounting_ledger_amount_precision()
