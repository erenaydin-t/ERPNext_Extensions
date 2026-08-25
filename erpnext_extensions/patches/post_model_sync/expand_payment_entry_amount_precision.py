# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT
"""Post-model-sync: verify/repair Payment Entry monetary columns to DECIMAL(30,9)."""

from __future__ import annotations

import frappe

from erpnext_extensions.payment_entry_decimal_precision import (
	apply_decimal_schema_targets,
	assert_schema_targets,
)


def execute() -> None:
	logger = frappe.logger("erpnext_extensions.expand_payment_entry_amount_precision")
	logger.info("Starting expand_payment_entry_amount_precision")
	results = apply_decimal_schema_targets(logger)
	errors = [row for row in results if row.get("status") == "error"]
	logger.info("Completed expand_payment_entry_amount_precision: %s rows", len(results))
	if errors:
		raise RuntimeError(
			"Payment Entry schema patch encountered unexpected errors:\n"
			+ "\n".join(f"{row['table']}.{row['field']}" for row in errors)
		)
	assert_schema_targets(logger)
