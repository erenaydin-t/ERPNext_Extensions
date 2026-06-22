# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT
"""Re-apply Stock Reconciliation DECIMAL(30,9) widen after table_exists fix in v1."""

from __future__ import annotations

from erpnext_extensions.patches.post_model_sync.expand_stock_reconciliation_amount_precision import (
	execute as expand_stock_reconciliation_amount_precision_execute,
)


def execute() -> None:
	expand_stock_reconciliation_amount_precision_execute()
