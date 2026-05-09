"""Remove **List View Settings** for **Cheque Book** if it pins only **ID**.

Saved list settings override DocType ``in_list_view`` and caused the list to show
only the name column. After removal, desk uses standard **Cheque Book** DocField flags.
"""

from __future__ import annotations

import json

import frappe


def execute():
	if not frappe.db.exists("List View Settings", "Cheque Book"):
		return

	try:
		raw = frappe.db.get_value("List View Settings", "Cheque Book", "fields") or "[]"
		fields = json.loads(raw) if isinstance(raw, str) else raw
	except Exception:
		fields = []

	# Only reset known-bad overrides (empty or ID-only). Preserve real user customizations.
	bad = (not fields) or (
		len(fields) == 1 and isinstance(fields[0], dict) and fields[0].get("fieldname") == "name"
	)
	if bad:
		frappe.delete_doc("List View Settings", "Cheque Book", ignore_permissions=True, force=True)
		frappe.reload_doctype("Cheque Book", force=True)
		frappe.clear_cache(doctype="Cheque Book")
