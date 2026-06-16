"""PM Holder display helpers for titles and link search."""

from __future__ import annotations

from typing import Any

import frappe
from frappe.utils import cint


def format_pm_holder_title(employee_name: str | None, employee: str | None, fallback: str = "") -> str:
	name = (employee_name or "").strip()
	code = (employee or "").strip()
	if name and code:
		return f"{name} ({code})"
	if name:
		return name
	if code:
		return code
	return fallback


def format_pm_holder_search_employee_line(employee_name: str | None, employee: str | None) -> str:
	name = (employee_name or "").strip()
	code = (employee or "").strip()
	if name and code:
		return f"{name} | {code}"
	return name or code


def pm_holder_query(doctype, txt, searchfield, start, page_len, filters):
	if doctype != "PM Holder":
		return []
	filters = _parse_filters(filters)
	conditions = ["1=1"]
	params: dict[str, Any] = {
		"txt": f"%{txt}%",
		"start": cint(start),
		"page_len": cint(page_len),
	}
	if txt:
		conditions.append(
			"""(
				h.name LIKE %(txt)s
				OR h.employee LIKE %(txt)s
				OR IFNULL(h.employee_name, '') LIKE %(txt)s
			)"""
		)
	for key in ("company", "employee", "petty_cash_account"):
		if filters.get(key):
			conditions.append(f"h.{key} = %({key})s")
			params[key] = filters[key]
	if filters.get("is_blocked") is not None:
		conditions.append("IFNULL(h.is_blocked, 0) = %(is_blocked)s")
		params["is_blocked"] = cint(filters.get("is_blocked"))

	where = " AND ".join(conditions)
	rows = frappe.db.sql(
		f"""
		SELECT
			h.name,
			IFNULL(h.employee_name, '') AS employee_name,
			IFNULL(h.employee, '') AS employee,
			IFNULL(c.company_name, h.company) AS company_name
		FROM `tabPM Holder` h
		LEFT JOIN `tabCompany` c ON c.name = h.company
		WHERE {where}
		ORDER BY h.employee_name, h.employee
		LIMIT %(page_len)s OFFSET %(start)s
		""",
		params,
		as_dict=True,
	)
	return [
		[
			row.name,
			format_pm_holder_title(row.employee_name, row.employee, row.name),
			row.company_name,
		]
		for row in rows
	]


def _parse_filters(filters):
	if isinstance(filters, str):
		filters = frappe.parse_json(filters) if filters else {}
	return filters or {}
