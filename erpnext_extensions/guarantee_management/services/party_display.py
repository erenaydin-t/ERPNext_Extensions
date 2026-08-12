# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT. See LICENSE file for details.

"""Resolve Guarantee Document party_type + party into business-friendly display.

Display values are never stored on Guarantee Document.
"""

from __future__ import annotations

from typing import Any

import frappe
from frappe.desk.reportview import get_filters_cond, get_match_cond
from frappe.utils import cstr


# party_type -> title field on the linked DocType
PARTY_TITLE_FIELDS: dict[str, str] = {
	"Customer": "customer_name",
	"Supplier": "supplier_name",
	"Employee": "employee_name",
	"Shareholder": "title",
	"Bank": "bank_name",
}

DOCTYPE_BACKED_PARTY_TYPES = frozenset(PARTY_TITLE_FIELDS.keys())


def format_party_display(
	party_type: str | None,
	party: str | None,
	other_party_name: str | None = None,
	title: str | None = None,
) -> str:
	"""Return a single business-friendly party label."""
	pt = (party_type or "").strip()
	if pt == "Other":
		return cstr(other_party_name or "").strip()

	code = cstr(party or "").strip()
	if not code:
		return ""

	if pt == "Bank":
		# Bank.name is autonamed from bank_name — display the bank name only.
		return cstr(title or code).strip() or code

	resolved_title = cstr(title or "").strip()
	if resolved_title and resolved_title != code:
		return f"{code} - {resolved_title}"
	return code


def batch_resolve_party_displays(refs: list[dict[str, Any]] | None) -> dict[str, str]:
	"""Batch-resolve display labels for a list of {party_type, party, other_party_name?}.

	Returns a map keyed by ``"{party_type}::{party}"`` (or ``"Other::{other_party_name}"``).
	Performs at most one query per distinct party_type — never per row.
	"""
	result: dict[str, str] = {}
	if not refs:
		return result

	by_type: dict[str, set[str]] = {}
	for ref in refs:
		pt = cstr(ref.get("party_type") or "").strip()
		if pt == "Other":
			other = cstr(ref.get("other_party_name") or "").strip()
			if other:
				result[_cache_key("Other", other)] = other
			continue
		party = cstr(ref.get("party") or "").strip()
		if not pt or not party:
			continue
		by_type.setdefault(pt, set()).add(party)

	for pt, names in by_type.items():
		title_field = PARTY_TITLE_FIELDS.get(pt)
		if not title_field or not frappe.db.exists("DocType", pt):
			for name in names:
				result[_cache_key(pt, name)] = name
			continue

		name_list = list(names)
		# Chunk large IN lists to keep SQL bounded.
		chunk_size = 500
		for i in range(0, len(name_list), chunk_size):
			chunk = name_list[i : i + chunk_size]
			rows = frappe.get_all(
				pt,
				filters={"name": ("in", chunk)},
				fields=["name", title_field],
				limit_page_length=len(chunk),
			)
			found = {cstr(r.name): cstr(r.get(title_field) or "") for r in rows}
			for name in chunk:
				result[_cache_key(pt, name)] = format_party_display(pt, name, title=found.get(name))

	return result


@frappe.whitelist()
def batch_resolve_party_displays_for_list(refs: str | list | None = None) -> dict[str, str]:
	"""Whitelisted wrapper for Guarantee Document List View batch display."""
	if isinstance(refs, str):
		refs = frappe.parse_json(refs) if refs else []
	if not isinstance(refs, list):
		refs = []
	return batch_resolve_party_displays(refs)


def get_party_display_from_doc(doc) -> str:
	"""Resolve display for a Guarantee Document-like object/dict."""
	pt = cstr(getattr(doc, "party_type", None) or (doc.get("party_type") if isinstance(doc, dict) else "")).strip()
	party = cstr(getattr(doc, "party", None) or (doc.get("party") if isinstance(doc, dict) else "")).strip()
	other = cstr(
		getattr(doc, "other_party_name", None) or (doc.get("other_party_name") if isinstance(doc, dict) else "")
	).strip()
	if pt == "Other":
		return format_party_display(pt, None, other_party_name=other)
	if not pt or not party:
		return ""
	title_field = PARTY_TITLE_FIELDS.get(pt)
	title = None
	if title_field and frappe.db.exists(pt, party):
		title = frappe.db.get_value(pt, party, title_field)
	return format_party_display(pt, party, title=title)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def party_search(doctype: str, txt: str, searchfield: str, start: int, page_len: int, filters: dict | None = None):
	"""Guarantee Document–scoped party link search (code + title where applicable)."""
	filters = filters or {}
	if isinstance(filters, str):
		filters = frappe.parse_json(filters) or {}

	party_type = cstr(filters.get("party_type") or doctype or "").strip()
	if party_type == "Other" or not party_type:
		return []
	if party_type not in DOCTYPE_BACKED_PARTY_TYPES:
		return []
	if doctype and doctype != party_type:
		# Dynamic Link always passes the target doctype as `doctype`.
		party_type = doctype
	if party_type not in DOCTYPE_BACKED_PARTY_TYPES:
		return []

	title_field = PARTY_TITLE_FIELDS[party_type]
	txt = cstr(txt or "")
	params: dict[str, Any] = {
		"txt": f"%{txt}%",
		"start": int(start or 0),
		"page_len": int(page_len or 20),
	}

	# Permission / user permission match conditions.
	match_cond = get_match_cond(party_type)
	filter_cond = ""
	# Drop party_type from filters passed to get_filters_cond (not a DocType field).
	link_filters = {k: v for k, v in filters.items() if k != "party_type"}
	if link_filters:
		filter_cond = get_filters_cond(party_type, link_filters, params, ignore_permissions=False)

	title_expr = f"`tab{party_type}`.`{title_field}`"
	search_clause = f"""
		(
			`tab{party_type}`.name LIKE %(txt)s
			OR IFNULL({title_expr}, '') LIKE %(txt)s
		)
	"""

	rows = frappe.db.sql(
		f"""
		SELECT
			`tab{party_type}`.name,
			IFNULL({title_expr}, '') AS title
		FROM `tab{party_type}`
		WHERE {search_clause}
			{filter_cond}
			{match_cond}
		ORDER BY
			CASE
				WHEN `tab{party_type}`.name LIKE %(txt)s THEN 0
				ELSE 1
			END,
			`tab{party_type}`.name
		LIMIT %(page_len)s OFFSET %(start)s
		""",
		params,
	)

	# Link search expects [value, description...] rows.
	out = []
	for name, title in rows:
		display = format_party_display(party_type, name, title=title)
		# description shows the composite label when different from name
		if party_type == "Bank":
			out.append([name, display])
		elif title and cstr(title) != cstr(name):
			out.append([name, display])
		else:
			out.append([name])
	return out


def _cache_key(party_type: str, party_or_other: str) -> str:
	return f"{party_type}::{party_or_other}"
