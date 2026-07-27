from __future__ import annotations

import frappe

from erpnext_extensions.approved_decimal_precision import apply_decimal_schema_targets


def execute() -> None:
	logger = frappe.logger("erpnext_extensions.expand_approved_monetary_amount_precision")
	logger.info("Starting expand_approved_monetary_amount_precision")
	results = apply_decimal_schema_targets(logger)
	errors = [row for row in results if row.get("status") == "error"]
	logger.info("Completed expand_approved_monetary_amount_precision: %s rows", len(results))
	if errors:
		raise RuntimeError(
			"Approved monetary schema patch encountered unexpected errors:\n"
			+ "\n".join(f"{row['table']}.{row['field']}" for row in errors)
		)
