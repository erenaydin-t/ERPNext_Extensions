# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT
"""Post-model-sync: verify/repair Stock Reconciliation amount columns to DECIMAL(30,9) (v4)."""

from __future__ import annotations

import frappe

from erpnext_extensions.stock_reconciliation_decimal_precision_v4 import apply_decimal_schema_targets


def execute() -> None:
	logger = frappe.logger("erpnext_extensions.expand_stock_reconciliation_amount_precision_v4")
	logger.info("Starting expand_stock_reconciliation_amount_precision_v4")
	results = apply_decimal_schema_targets(logger)
	errors = [row for row in results if row.get("status") == "error"]
	logger.info("Completed expand_stock_reconciliation_amount_precision_v4: %s rows", len(results))
	if errors:
		raise RuntimeError(
			"Stock Reconciliation schema patch encountered unexpected errors:\n"
			+ "\n".join(f"{row['table']}.{row['field']}" for row in errors)
		)
