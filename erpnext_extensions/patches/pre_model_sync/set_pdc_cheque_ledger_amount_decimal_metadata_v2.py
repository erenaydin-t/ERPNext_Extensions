# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT
"""Pre-model-sync: durable length=30 metadata for PDC / Cheque / Ledger amount fields."""

from __future__ import annotations

import frappe

from erpnext_extensions.cheque_management.pdc_decimal_precision_v2 import verify_and_set_metadata


def execute() -> None:
	logger = frappe.logger("erpnext_extensions.set_pdc_cheque_ledger_amount_decimal_metadata_v2")
	logger.info("Starting set_pdc_cheque_ledger_amount_decimal_metadata_v2")
	results = verify_and_set_metadata(logger)
	errors = [row for row in results if row.get("status") == "error"]
	logger.info("Completed set_pdc_cheque_ledger_amount_decimal_metadata_v2: %s rows", len(results))
	if errors:
		raise RuntimeError(
			"PDC cheque/ledger metadata patch encountered unexpected errors:\n"
			+ "\n".join(f"{row['doctype']}.{row['field']}" for row in errors)
		)
