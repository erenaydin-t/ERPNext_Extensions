"""Backfill empty Facility Settings JE template fields with Persian defaults."""

from __future__ import annotations

import frappe

from erpnext_extensions.facility_management.facility_settings_doc import (
	FACILITY_SETTINGS_TEMPLATE_DEFAULTS,
	populate_facility_settings_template_defaults,
)


def execute():
	for name in frappe.get_all("Facility Settings", pluck="name"):
		doc = frappe.get_doc("Facility Settings", name)
		before = {fn: doc.get(fn) for fn in FACILITY_SETTINGS_TEMPLATE_DEFAULTS}
		populate_facility_settings_template_defaults(doc)
		changed = any(before[fn] != doc.get(fn) for fn in FACILITY_SETTINGS_TEMPLATE_DEFAULTS)
		if changed:
			doc.save(ignore_permissions=True)
	frappe.db.commit()
