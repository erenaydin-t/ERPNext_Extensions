# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT
"""Pre-model-sync: durable length=30 metadata for Payment Entry monetary fields."""

from __future__ import annotations

import frappe

from erpnext_extensions.payment_entry_decimal_precision import verify_and_set_metadata


def execute() -> None:
	logger = frappe.logger("erpnext_extensions.set_payment_entry_amount_decimal_metadata")
	logger.info("Starting set_payment_entry_amount_decimal_metadata")
	results = verify_and_set_metadata(logger)
	errors = [row for row in results if row.get("status") == "error"]
	logger.info("Completed set_payment_entry_amount_decimal_metadata: %s rows", len(results))
	if errors:
		raise RuntimeError(
			"Payment Entry metadata patch encountered unexpected errors:\n"
			+ "\n".join(f"{row['doctype']}.{row['field']}" for row in errors)
		)
