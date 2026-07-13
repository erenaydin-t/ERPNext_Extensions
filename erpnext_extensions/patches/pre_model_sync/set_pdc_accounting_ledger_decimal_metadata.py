# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT
"""Property setters so migrate sync keeps DECIMAL(30,9) on Payment Ledger Entry (PDC JE path).

Journal Entry Account / GL Entry metadata are covered by set_gl_entry_amount_decimal_metadata
and set_pdc_cheque_amount_decimal_metadata for PDC DocTypes. Avoids re-validating Journal Entry
DocType on sites with custom/broken Link options.
"""

from __future__ import annotations

import frappe
from frappe.custom.doctype.property_setter.property_setter import make_property_setter
from frappe.utils import cint

TARGET_LENGTH = 30
JE_WORDS_MAX_LENGTH = 300

PAYMENT_LEDGER_AMOUNT_FIELDS: tuple[str, ...] = ("amount", "amount_in_account_currency")


def _ensure_length_property_setter(doctype: str, fieldname: str, logger) -> None:
	filters = {
		"doc_type": doctype,
		"field_name": fieldname,
		"property": "length",
		"doctype_or_field": "DocField",
	}
	existing_name = frappe.db.get_value("Property Setter", filters, "name")
	current_value = frappe.db.get_value("Property Setter", filters, "value") if existing_name else None

	if current_value is not None and cint(current_value) >= TARGET_LENGTH:
		logger.info(
			"Skipping %s.%s: length property setter already %s (>=%s)",
			doctype,
			fieldname,
			current_value,
			TARGET_LENGTH,
		)
		return

	if existing_name:
		frappe.db.set_value("Property Setter", existing_name, "value", str(TARGET_LENGTH))
		logger.info(
			"Updated Property Setter %s: %s.%s length -> %s", existing_name, doctype, fieldname, TARGET_LENGTH
		)
		return

	make_property_setter(
		doctype,
		fieldname,
		"length",
		str(TARGET_LENGTH),
		"Int",
		is_system_generated=True,
		validate_fields_for_doctype=False,
	)
	logger.info("Created Property Setter: %s.%s length -> %s", doctype, fieldname, TARGET_LENGTH)


def _ensure_je_words_varchar_length(logger) -> None:
	"""Frappe _validate_length uses DocField `length` for Data/varchar, not max_length."""
	if not frappe.db.exists("DocType", "Journal Entry"):
		return
	doctype = "Journal Entry"
	fieldname = "total_amount_in_words"
	for prop in ("length", "max_length"):
		filters = {
			"doc_type": doctype,
			"field_name": fieldname,
			"property": prop,
			"doctype_or_field": "DocField",
		}
		existing_name = frappe.db.get_value("Property Setter", filters, "name")
		current_value = frappe.db.get_value("Property Setter", filters, "value") if existing_name else None
		if current_value is not None and cint(current_value) >= JE_WORDS_MAX_LENGTH:
			continue
		if existing_name:
			frappe.db.set_value("Property Setter", existing_name, "value", str(JE_WORDS_MAX_LENGTH))
			logger.info(
				"Updated Property Setter %s: %s.%s %s -> %s",
				existing_name,
				doctype,
				fieldname,
				prop,
				JE_WORDS_MAX_LENGTH,
			)
			continue
		make_property_setter(
			doctype,
			fieldname,
			prop,
			str(JE_WORDS_MAX_LENGTH),
			"Int",
			is_system_generated=True,
			validate_fields_for_doctype=False,
		)
		logger.info("Created Property Setter: %s.%s %s -> %s", doctype, fieldname, prop, JE_WORDS_MAX_LENGTH)
	logger.info("Ensured Journal Entry.total_amount_in_words length/max_length >= %s", JE_WORDS_MAX_LENGTH)
	frappe.clear_cache(doctype="Journal Entry")


def execute() -> None:
	logger = frappe.logger("erpnext_extensions.set_pdc_accounting_ledger_decimal_metadata")
	logger.info("Starting set_pdc_accounting_ledger_decimal_metadata")

	doctype = "Payment Ledger Entry"
	if frappe.db.exists("DocType", doctype):
		meta = frappe.get_meta(doctype, cached=False)
		known = {df.fieldname for df in meta.fields}
		for fieldname in PAYMENT_LEDGER_AMOUNT_FIELDS:
			if fieldname not in known:
				logger.warning("Skipping unknown field %s on %s", fieldname, doctype)
				continue
			_ensure_length_property_setter(doctype, fieldname, logger)
		frappe.clear_cache(doctype=doctype)

	_ensure_je_words_varchar_length(logger)

	logger.info("Completed set_pdc_accounting_ledger_decimal_metadata")
	frappe.db.commit()
