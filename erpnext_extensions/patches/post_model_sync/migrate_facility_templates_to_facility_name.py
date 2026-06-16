"""Migrate Facility Settings JE templates from {facility_number} defaults to {facility_name}."""

from __future__ import annotations

import frappe

from erpnext_extensions.facility_management.facility_settings_doc import (
	FACILITY_SETTINGS_TEMPLATE_DEFAULTS,
	LEGACY_FACILITY_SETTINGS_TEMPLATE_DEFAULTS,
	migrate_facility_settings_templates_to_facility_name,
)


def execute():
	for name in frappe.get_all("Facility Settings", pluck="name"):
		doc = frappe.get_doc("Facility Settings", name)
		if migrate_facility_settings_templates_to_facility_name(doc):
			doc.save(ignore_permissions=True)

	for fac_name in frappe.get_all("Facility", pluck="name"):
		doc = frappe.get_doc("Facility", fac_name)
		changed = False
		for fac_fn, settings_fn in (
			("receipt_remarks_template", "default_receipt_remarks_template"),
			("repayment_remarks_template", "default_repayment_remarks_template"),
		):
			val = doc.get(fac_fn)
			if not val or not str(val).strip():
				continue
			legacy = LEGACY_FACILITY_SETTINGS_TEMPLATE_DEFAULTS.get(settings_fn)
			new = FACILITY_SETTINGS_TEMPLATE_DEFAULTS.get(settings_fn)
			if legacy and new and str(val).strip() == legacy.strip() and str(val).strip() != new.strip():
				doc.set(fac_fn, new)
				changed = True
		if changed:
			doc.save(ignore_permissions=True)

	frappe.db.commit()
