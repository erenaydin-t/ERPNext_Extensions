# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

import frappe
from frappe.desk.reportview import build_match_conditions
from frappe.utils import cint


def facility_names_for_report_filters(filters) -> list[str]:
	"""Resolve Facility IDs from report filters (exact facility link and/or partial facility_name)."""
	filters = frappe._dict(filters or {})
	if not filters.get("company"):
		frappe.throw(frappe._("Company is required"))
	if filters.get("facility"):
		name = filters.facility
		if filters.get("facility_name"):
			match = frappe.db.get_value(
				"Facility",
				{"name": name, "company": filters.company, "facility_name": ("like", f"%{filters.facility_name.strip()}%")},
			)
			if not match:
				return []
		return [name]

	conditions = ["f.company = %(company)s"]
	params: dict = {"company": filters.company}
	if filters.get("bank"):
		conditions.append("f.bank = %(bank)s")
		params["bank"] = filters.bank
	if filters.get("status"):
		conditions.append("f.status = %(status)s")
		params["status"] = filters.status
	if filters.get("facility_name"):
		conditions.append("f.facility_name LIKE %(facility_name)s")
		params["facility_name"] = f"%{filters.facility_name.strip()}%"

	return frappe.db.sql_list(
		f"""
		SELECT f.name FROM `tabFacility` f
		WHERE {' AND '.join(conditions)}
		ORDER BY f.name
		""",
		params,
	)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def facility_link_query(doctype, txt, searchfield, start, page_len, filters):
	"""Link search: Facility ID, facility name, facility number (name), bank."""
	filters = frappe._dict(filters or {})
	start = cint(start)
	page_len = cint(page_len) or 20
	txt = f"%{txt}%"
	conditions = ["(f.name LIKE %(txt)s OR f.facility_name LIKE %(txt)s OR f.bank LIKE %(txt)s)"]
	params: dict = {"txt": txt, "start": start, "page_len": page_len}

	if filters.get("company"):
		conditions.append("f.company = %(company)s")
		params["company"] = filters.company
	if filters.get("status"):
		conditions.append("f.status = %(status)s")
		params["status"] = filters.status

	match_conditions = build_match_conditions("Facility")
	if match_conditions:
		conditions.append(match_conditions)

	return frappe.db.sql(
		f"""
		SELECT f.name, f.facility_name, f.bank, f.status
		FROM `tabFacility` f
		WHERE {' AND '.join(conditions)}
		ORDER BY f.modified DESC
		LIMIT %(page_len)s OFFSET %(start)s
		""",
		params,
	)
