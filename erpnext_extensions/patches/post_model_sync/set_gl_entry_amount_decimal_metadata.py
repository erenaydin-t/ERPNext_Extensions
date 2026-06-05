# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT
"""Set GL Entry amount/currency field metadata so Frappe sync targets DECIMAL(30,9).

Uses Property Setter on DocField `length` (width). With field `precision` 9 (DocType default
or explicit), Frappe's get_definition() yields decimal(30,9) for Currency/Float columns.

Idempotent: skips when an existing length property setter is already >= 30.
"""

from __future__ import annotations

import frappe
from frappe.custom.doctype.property_setter.property_setter import make_property_setter
from frappe.utils import cint

DOCTYPE = "GL Entry"
TARGET_LENGTH = 30

GL_ENTRY_AMOUNT_FIELDS: tuple[str, ...] = (
	"transaction_exchange_rate",
	"debit_in_account_currency",
	"debit",
	"debit_in_transaction_currency",
	"credit_in_account_currency",
	"credit",
	"credit_in_transaction_currency",
	"reporting_currency_exchange_rate",
	"debit_in_reporting_currency",
	"credit_in_reporting_currency",
)


def _ensure_length_property_setter(fieldname: str, logger) -> None:
	filters = {
		"doc_type": DOCTYPE,
		"field_name": fieldname,
		"property": "length",
		"doctype_or_field": "DocField",
	}
	existing_name = frappe.db.get_value("Property Setter", filters, "name")
	current_value = frappe.db.get_value("Property Setter", filters, "value") if existing_name else None

	if current_value is not None and cint(current_value) >= TARGET_LENGTH:
		logger.info(
			"Skipping %s.%s: length property setter already %s (>=%s)",
			DOCTYPE,
			fieldname,
			current_value,
			TARGET_LENGTH,
		)
		return

	if existing_name:
		frappe.db.set_value("Property Setter", existing_name, "value", str(TARGET_LENGTH))
		logger.info(
			"Updated Property Setter %s: %s.%s length -> %s",
			existing_name,
			DOCTYPE,
			fieldname,
			TARGET_LENGTH,
		)
		return

	make_property_setter(
		DOCTYPE,
		fieldname,
		"length",
		str(TARGET_LENGTH),
		"Int",
		is_system_generated=True,
	)
	logger.info("Created Property Setter: %s.%s length -> %s", DOCTYPE, fieldname, TARGET_LENGTH)


def execute() -> None:
	logger = frappe.logger("erpnext_extensions.set_gl_entry_amount_decimal_metadata")
	logger.info("Starting set_gl_entry_amount_decimal_metadata")

	meta = frappe.get_meta(DOCTYPE, cached=False)
	known_fields = {df.fieldname for df in meta.fields}

	for fieldname in GL_ENTRY_AMOUNT_FIELDS:
		if fieldname not in known_fields:
			logger.warning("Skipping unknown field %s on %s", fieldname, DOCTYPE)
			continue
		_ensure_length_property_setter(fieldname, logger)

	frappe.clear_cache(doctype=DOCTYPE)
	logger.info("Completed set_gl_entry_amount_decimal_metadata")
	frappe.db.commit()
