# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT
"""Pre-model-sync: durable length=30 metadata for Accounting Core amount fields."""

from __future__ import annotations

import frappe

from erpnext_extensions.accounting_core_decimal_precision import verify_and_set_metadata


def execute() -> None:
	logger = frappe.logger("erpnext_extensions.set_accounting_core_amount_decimal_metadata_v2")
	logger.info("Starting set_accounting_core_amount_decimal_metadata_v2")
	results = verify_and_set_metadata(logger)
	errors = [row for row in results if row.get("status") == "error"]
	logger.info("Completed set_accounting_core_amount_decimal_metadata_v2: %s rows", len(results))
	if errors:
		raise RuntimeError(
			"Accounting core metadata patch encountered unexpected errors:\n"
			+ "\n".join(f"{row['doctype']}.{row['field']}" for row in errors)
		)
