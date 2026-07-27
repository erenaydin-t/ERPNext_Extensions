# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT
"""Post-model-sync: verify/repair Accounting Core amount columns to DECIMAL(30,9)."""

from __future__ import annotations

import frappe

from erpnext_extensions.accounting_core_decimal_precision import apply_decimal_schema_targets


def execute() -> None:
	logger = frappe.logger("erpnext_extensions.expand_accounting_core_amount_precision_v2")
	logger.info("Starting expand_accounting_core_amount_precision_v2")
	results = apply_decimal_schema_targets(logger)
	errors = [row for row in results if row.get("status") == "error"]
	logger.info("Completed expand_accounting_core_amount_precision_v2: %s rows", len(results))
	if errors:
		raise RuntimeError(
			"Accounting core schema patch encountered unexpected errors:\n"
			+ "\n".join(f"{row['table']}.{row['field']}" for row in errors)
		)
