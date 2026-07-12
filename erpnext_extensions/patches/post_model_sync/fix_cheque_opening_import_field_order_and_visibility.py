"""Cheque Opening Import — strict verification / finalization (second pass).

Purpose
-------
- **Fail-fast** validation: raises if any DocField in `REQUIRED_ORDER` is missing after
  `reload_doc`, surfacing seriously incomplete schema state early.
- **Exact ordering** for the **core import layout block** only: sets `DocField.idx`
  sequentially (1…n) for the fields listed in `REQUIRED_ORDER`.
- Ensures visibility and HTML field type for the same key fields as the first pass.

Relationship to `fix_cheque_opening_import_meta.py`
---------------------------------------------------
The meta patch is a **broad, tolerant** repair (full-field reindex, optional
`DocType.field_order`, no hard failure when individual rows are missing). This patch is
a **stricter consistency check** intended to run **after** that softer recovery.

**Overlap is intentional historically**; both stay in `patches.txt` for **migration
safety and history**. Consolidation may be considered later after broader migration
confidence — not part of this phase.

Do not change validation or commit behavior here without an explicit cleanup phase.
"""

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


def _get_docfields() -> list[dict[str, Any]]:
	return frappe.get_all(
		"DocField",
		filters={"parent": DOCTYPE},
		fields=["name", "fieldname", "fieldtype", "label", "idx", "hidden", "read_only"],
		order_by="idx asc",
	)


def diagnose() -> dict[str, Any]:
	"""Manual diagnostic helper (e.g. `bench execute`); **not** used by `execute()` / migrate."""
	fields = _get_docfields()
	meta = frappe.get_meta(DOCTYPE)
	exists = {f["fieldname"] for f in fields}
	return {
		"doctype": DOCTYPE,
		"docfield_count": len(fields),
		"docfields": fields,
		"meta_field_order": getattr(meta, "field_order", None),
		"missing_required_order_fields": [f for f in REQUIRED_ORDER if f not in exists],
		"missing_required_visible_fields": [f for f in REQUIRED_VISIBLE_FIELDS if f not in exists],
	}


def execute():
	# Ensure JSON definition is applied to DB first.
	frappe.reload_doc("cheque_management", "doctype", "cheque_opening_import", force=True)

	fields = _get_docfields()
	by_fieldname = {f["fieldname"]: f for f in fields}

	missing = [f for f in REQUIRED_ORDER if f not in by_fieldname]
	if missing:
		raise frappe.ValidationError(f"{DOCTYPE}: missing DocField rows for {', '.join(missing)}")

	# Fix types/visibility first.
	html_df_name = by_fieldname["import_template_actions_html"]["name"]
	frappe.db.set_value("DocField", html_df_name, "fieldtype", "HTML")
	frappe.db.set_value("DocField", html_df_name, "hidden", 0)

	for fieldname in REQUIRED_VISIBLE_FIELDS:
		df_name = by_fieldname[fieldname]["name"]
		frappe.db.set_value("DocField", df_name, "hidden", 0)

	# Apply required idx ordering exactly.
	for idx, fieldname in enumerate(REQUIRED_ORDER, start=1):
		df_name = by_fieldname[fieldname]["name"]
		frappe.db.set_value("DocField", df_name, "idx", idx)

	frappe.clear_cache(doctype=DOCTYPE)
	frappe.db.commit()
