# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT
"""Pre-model-sync: durable length=30 metadata for Stock Reconciliation amount fields (v4)."""

from __future__ import annotations

import frappe

from erpnext_extensions.stock_reconciliation_decimal_precision_v4 import verify_and_set_metadata


def execute() -> None:
	logger = frappe.logger("erpnext_extensions.set_stock_reconciliation_amount_decimal_metadata_v4")
	logger.info("Starting set_stock_reconciliation_amount_decimal_metadata_v4")
	results = verify_and_set_metadata(logger)
	errors = [row for row in results if row.get("status") == "error"]
	logger.info("Completed set_stock_reconciliation_amount_decimal_metadata_v4: %s rows", len(results))
	if errors:
		raise RuntimeError(
			"Stock Reconciliation metadata patch encountered unexpected errors:\n"
			+ "\n".join(f"{row['doctype']}.{row['field']}" for row in errors)
		)
