"""Create Facility Type master records and migrate Facility.facility_type links."""

from __future__ import annotations

import frappe

from erpnext_extensions.facility_management.facility_type_data import (
	ensure_default_facility_types,
	migrate_facility_type_links,
)


def execute():
	frappe.reload_doc("facility_management", "doctype", "facility_type")
	ensure_default_facility_types()
	migrate_facility_type_links()
	frappe.db.commit()
