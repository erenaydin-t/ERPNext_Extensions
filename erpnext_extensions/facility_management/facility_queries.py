# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

import frappe
from frappe.desk.reportview import build_match_conditions
from frappe.utils import cint


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def facility_type_link_query(doctype, txt, searchfield, start, page_len, filters):
	txt = f"%{txt}%"
	return frappe.db.sql(
		"""
		SELECT name, facility_type_name
		FROM `tabFacility Type`
		WHERE disabled = 0
			AND (facility_type_name LIKE %(txt)s OR name LIKE %(txt)s)
		ORDER BY facility_type_name ASC
		LIMIT %(page_len)s OFFSET %(start)s
		""",
		{"txt": txt, "start": cint(start), "page_len": cint(page_len)},
	)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def facility_link_query(doctype, txt, searchfield, start, page_len, filters):
	"""Search Facility by ID, facility name, and bank (Active facilities for repayments)."""
	filters = frappe._dict(filters or {})
	txt = f"%{txt}%"
	conditions = [
		"(name LIKE %(txt)s OR facility_name LIKE %(txt)s OR bank LIKE %(txt)s OR IFNULL(remarks, '') LIKE %(txt)s)"
	]
	params = {"txt": txt, "start": cint(start), "page_len": cint(page_len)}

	if filters.get("company"):
		conditions.append("company = %(company)s")
		params["company"] = filters.company
	if filters.get("status"):
		conditions.append("status = %(status)s")
		params["status"] = filters.status
	elif filters.get("repayment_select"):
		conditions.append("status = 'Active'")

	match_conditions = build_match_conditions("Facility")
	if match_conditions:
		conditions.append(match_conditions)

	return frappe.db.sql(
		f"""
		SELECT name, facility_name, bank, status
		FROM `tabFacility`
		WHERE {" AND ".join(conditions)}
		ORDER BY facility_name ASC, name ASC
		LIMIT %(page_len)s OFFSET %(start)s
		""",
		params,
	)


def facility_names_matching(company: str, facility_name: str, *, exact_facility: str | None = None) -> list[str]:
	"""Partial match on Facility.facility_name within company."""
	if exact_facility:
		return [exact_facility]
	if not (facility_name or "").strip():
		return []
	return frappe.get_all(
		"Facility",
		filters={"company": company, "facility_name": ["like", f"%{facility_name.strip()}%"]},
		pluck="name",
		order_by="name asc",
	)
