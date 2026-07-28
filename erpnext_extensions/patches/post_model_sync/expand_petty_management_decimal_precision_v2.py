# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT
"""Post-model-sync: verify/repair Petty Management amount columns to DECIMAL(30,9) (v2)."""

from __future__ import annotations

import frappe

from erpnext_extensions.petty_management_decimal_precision_v2 import apply_decimal_schema_targets


def execute() -> None:
	logger = frappe.logger("erpnext_extensions.expand_petty_management_decimal_precision_v2")
	logger.info("Starting expand_petty_management_decimal_precision_v2")
	results = apply_decimal_schema_targets(logger)
	errors = [row for row in results if row.get("status") == "error"]
	logger.info("Completed expand_petty_management_decimal_precision_v2: %s rows", len(results))
	if errors:
		raise RuntimeError(
			"Petty Management schema patch encountered unexpected errors:\n"
			+ "\n".join(f"{row['table']}.{row['field']}" for row in errors)
		)
