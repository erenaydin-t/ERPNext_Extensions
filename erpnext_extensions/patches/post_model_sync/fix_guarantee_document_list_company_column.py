"""Ensure Guarantee Document Company is filterable but not a default list column.

v4.3.0 removed ``in_list_view`` from Company in DocType JSON. Sites that still
have ``in_list_view=1`` on DocField, or List View Settings that pin Company,
continue to show the column until corrected.
"""

from __future__ import annotations

import json

import frappe


DOCTYPE = "Guarantee Document"


def execute():
	if not frappe.db.exists("DocType", DOCTYPE):
		return

	frappe.db.sql(
		"""
		UPDATE `tabDocField`
		SET in_list_view = 0
		WHERE parent = %s AND fieldname = 'company'
		""",
		DOCTYPE,
	)

	if frappe.db.exists("List View Settings", DOCTYPE):
		raw = frappe.db.get_value("List View Settings", DOCTYPE, "fields") or "[]"
		try:
			fields = json.loads(raw) if isinstance(raw, str) else raw
		except Exception:
			fields = []

		if isinstance(fields, list) and fields:
			cleaned = [
				f
				for f in fields
				if (f if isinstance(f, str) else (f or {}).get("fieldname")) != "company"
			]
			if len(cleaned) != len(fields):
				frappe.db.set_value(
					"List View Settings",
					DOCTYPE,
					"fields",
					json.dumps(cleaned),
					update_modified=False,
				)

	frappe.clear_cache(doctype=DOCTYPE)
