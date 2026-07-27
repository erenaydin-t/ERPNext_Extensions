from __future__ import annotations

import frappe

from erpnext_extensions.approved_decimal_precision import verify_and_set_metadata


def execute() -> None:
	logger = frappe.logger("erpnext_extensions.set_approved_monetary_decimal_metadata")
	logger.info("Starting set_approved_monetary_decimal_metadata")
	results = verify_and_set_metadata(logger)
	errors = [row for row in results if row.get("status") == "error"]
	logger.info("Completed set_approved_monetary_decimal_metadata: %s rows", len(results))
	if errors:
		raise RuntimeError(
			"Approved monetary metadata patch encountered unexpected errors:\n"
			+ "\n".join(f"{row['doctype']}.{row['field']}" for row in errors)
		)
