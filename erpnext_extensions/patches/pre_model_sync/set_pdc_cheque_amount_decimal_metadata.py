# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT
"""Set Post Dated Cheque / child amount field metadata so migrate sync keeps DECIMAL(30,9).

Runs in pre_model_sync so Property Setters exist before DocType ``updatedb`` during sync.
"""

from __future__ import annotations

import frappe
from frappe.custom.doctype.property_setter.property_setter import make_property_setter
from frappe.utils import cint

TARGET_LENGTH = 30

FIELDS_BY_DOCTYPE: dict[str, tuple[str, ...]] = {
	"Post Dated Cheque": ("cheque_amount", "allocated_amount", "unallocated_amount"),
	"PDC Allocation": ("amount",),
	"PDC Journal Reference": ("amount",),
	"Guarantee Document": ("amount",),
}


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
	)
	logger.info("Created Property Setter: %s.%s length -> %s", doctype, fieldname, TARGET_LENGTH)


def execute() -> None:
	logger = frappe.logger("erpnext_extensions.set_pdc_cheque_amount_decimal_metadata")
	logger.info("Starting set_pdc_cheque_amount_decimal_metadata")

	for doctype, fields in FIELDS_BY_DOCTYPE.items():
		if not frappe.db.exists("DocType", doctype):
			logger.warning("Skipping missing DocType %s", doctype)
			continue
		meta = frappe.get_meta(doctype, cached=False)
		known = {df.fieldname for df in meta.fields}
		for fieldname in fields:
			if fieldname not in known:
				logger.warning("Skipping unknown field %s on %s", fieldname, doctype)
				continue
			_ensure_length_property_setter(doctype, fieldname, logger)
		frappe.clear_cache(doctype=doctype)

	logger.info("Completed set_pdc_cheque_amount_decimal_metadata")
	frappe.db.commit()
