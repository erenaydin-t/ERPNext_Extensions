from __future__ import annotations

import json
from typing import Any

import frappe


DOCTYPE = "Cheque Opening Import"

REQUIRED_VISIBLE_FIELDS = ("import_file", "import_status", "summary", "items")

REQUIRED_ORDER = (
	"section_import",
	"import_file",
	"column_break_1",
	"import_status",
	"import_template_actions_html",
	"section_summary",
	"summary",
	"section_items",
	"items",
)


def _docfields_state() -> list[dict[str, Any]]:
	return frappe.get_all(
		"DocField",
		filters={"parent": DOCTYPE},
		fields=["name", "fieldname", "fieldtype", "label", "idx", "hidden", "read_only"],
		order_by="idx asc",
	)


def get_state() -> dict[str, Any]:
	"""Runtime diagnosis helper (safe to call via bench execute)."""
	field_order_value = None
	if frappe.db.has_column("DocType", "field_order"):
		field_order_value = frappe.db.get_value("DocType", DOCTYPE, "field_order")

	property_setters = frappe.get_all(
		"Property Setter",
		filters={"doc_type": DOCTYPE},
		fields=["name", "field_name", "property", "value", "property_type"],
		order_by="creation asc",
	)

	doctype_layouts = []
	if frappe.db.exists("DocType", "DocType Layout"):
		try:
			doctype_layouts = frappe.get_all(
				"DocType Layout",
				filters={"document_type": DOCTYPE},
				fields=["name", "route", "disabled"],
				order_by="modified desc",
			)
		except Exception:
			# Keep diagnosis resilient across framework versions / schemas
			doctype_layouts = [{"error": "Failed to query DocType Layout fields"}]
	return {
		"doctype": DOCTYPE,
		"doctype_field_order": field_order_value,
		"docfields": _docfields_state(),
		"property_setters": property_setters,
		"doctype_layouts": doctype_layouts,
		"exists": {
			f: bool(frappe.db.exists("DocField", {"parent": DOCTYPE, "fieldname": f}))
			for f in (
				"import_file",
				"import_status",
				"import_template_actions_html",
				"summary",
				"items",
			)
		},
	}


def run() -> None:
	"""
	Fix broken form layout caused by bad/mismatched DocField order in DB.

	- Force reload doctype from filesystem
	- Ensure required fields exist and are visible
	- Normalize `idx` ordering + `field_order` string on DocType
	- Clear caches so desk picks up corrected meta
	"""
	# 1) Reload from filesystem (ensures DocField rows exist / correct types)
	frappe.reload_doc("cheque_management", "doctype", "cheque_opening_import", force=True)

	# 2) Re-fetch after reload
	docfields = _docfields_state()
	by_fieldname = {d.get("fieldname"): d for d in docfields if d.get("fieldname")}

	# 3) Ensure the new HTML field exists and is correct
	html_df = by_fieldname.get("import_template_actions_html")
	if html_df:
		frappe.db.set_value("DocField", html_df["name"], "fieldtype", "HTML")
		frappe.db.set_value("DocField", html_df["name"], "hidden", 0)

	# 4) Ensure important fields are not hidden
	for fn in REQUIRED_VISIBLE_FIELDS:
		df = by_fieldname.get(fn)
		if df:
			frappe.db.set_value("DocField", df["name"], "hidden", 0)

	# 5) Normalize idx order (keep existing fields but enforce the required order first)
	dt = frappe.get_doc("DocType", DOCTYPE)
	fieldnames_in_dt = [f.fieldname for f in dt.fields if f.fieldname]

	ordered = [f for f in REQUIRED_ORDER if f in fieldnames_in_dt]
	ordered += [f for f in fieldnames_in_dt if f not in ordered]

	# Update idx on DocField rows
	df_rows = frappe.get_all(
		"DocField",
		filters={"parent": DOCTYPE},
		fields=["name", "fieldname"],
	)
	name_by_fieldname = {r["fieldname"]: r["name"] for r in df_rows if r.get("fieldname")}

	for i, fieldname in enumerate(ordered, start=1):
		row_name = name_by_fieldname.get(fieldname)
		if row_name:
			frappe.db.set_value("DocField", row_name, "idx", i)

	# Update DocType.field_order if column exists (some versions don't store it)
	if frappe.db.has_column("DocType", "field_order"):
		frappe.db.set_value("DocType", DOCTYPE, "field_order", json.dumps(ordered))

	# 6) Clear caches so UI rebuilds layout
	frappe.clear_cache(doctype=DOCTYPE)
	frappe.clear_cache()


def execute() -> None:
	# Frappe patch runner looks for `execute()` by default.
	run()

