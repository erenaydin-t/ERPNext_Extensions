# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

import frappe
from frappe import _

from erpnext_extensions.facility_management.facility_queries import facility_names_matching


def apply_facility_filters_to_sql(conditions: list[str], params: dict, filters) -> None:
	"""Add facility / facility_name filters to Facility list SQL."""
	if filters.get("facility"):
		conditions.append("name = %(facility)s")
		params["facility"] = filters.facility
	elif filters.get("facility_name"):
		names = facility_names_matching(filters.company, filters.facility_name)
		if not names:
			conditions.append("1=0")
			return
		conditions.append("name IN %(facility_names)s")
		params["facility_names"] = tuple(names)
	if filters.get("facility_type"):
		conditions.append("facility_type = %(facility_type)s")
		params["facility_type"] = filters.facility_type


def resolve_ledger_facility(filters) -> str:
	"""Resolve single facility for ledger from facility or facility_name filter."""
	if filters.get("facility"):
		facility = filters.facility
		if filters.get("facility_type"):
			ft = frappe.db.get_value("Facility", facility, "facility_type")
			if ft != filters.facility_type:
				frappe.throw(_("Facility does not match the selected Facility Type."))
		return facility
	name_part = (filters.get("facility_name") or "").strip()
	if not name_part and not filters.get("facility_type"):
		frappe.throw(_("Facility or Facility Name is required."))
	names = facility_names_matching(filters.company, name_part) if name_part else frappe.get_all(
		"Facility",
		filters={"company": filters.company},
		pluck="name",
	)
	if filters.get("facility_type"):
		names = [
			n
			for n in names
			if frappe.db.get_value("Facility", n, "facility_type") == filters.facility_type
		]
	if not names:
		frappe.throw(_("No facility found for the selected filters."))
	if len(names) > 1:
		frappe.throw(
			_("Multiple facilities match. Select a Facility or use a more specific Facility Name.")
		)
	return names[0]
