# Copyright (c) 2026, ERPNext Extensions contributors
"""v4.1.4: simplify PM roles + rebuild workflows for User/Accountant model (idempotent).

Does not mutate business amounts, Payment Entries, or payment_status on existing docs.
Legacy roles remain in the database (deprecated) for one release for backward compatibility.
"""

from __future__ import annotations

import frappe

from erpnext_extensions.patches.post_model_sync.migrate_pm_workflow_v402 import (
	_rebuild_pm_clearance_workflow,
	_rebuild_pm_request_workflow,
	_seed_assignment_rules,
)

DEPRECATED_PM_ROLES = (
	"Petty Management Manager",
	"Petty Management Admin",
	"Petty Management Auditor",
)

# DocPerm targets after role collapse (JSON + Custom DocPerm sync).
# Migration notes are also in RELEASE_4_1_4.md.
DOCTYPE_PERMS = {
	"PM Request": [
		{
			"role": "System Manager",
			"read": 1,
			"write": 1,
			"create": 1,
			"delete": 1,
			"submit": 1,
			"cancel": 1,
			"amend": 1,
			"report": 1,
		},
		{
			"role": "Petty Management User",
			"read": 1,
			"write": 1,
			"create": 1,
			"submit": 1,
			"report": 1,
		},
		{
			"role": "Petty Management Accountant",
			"read": 1,
			"write": 1,
			"create": 1,
			"submit": 1,
			"cancel": 1,
			"amend": 1,
			"report": 1,
		},
	],
	"PM Clearance": [
		{
			"role": "System Manager",
			"read": 1,
			"write": 1,
			"create": 1,
			"delete": 1,
			"submit": 1,
			"cancel": 1,
			"amend": 1,
			"report": 1,
		},
		{
			"role": "Petty Management User",
			"read": 1,
			"write": 1,
			"create": 1,
			"submit": 1,
			"report": 1,
		},
		{
			"role": "Petty Management Accountant",
			"read": 1,
			"write": 1,
			"create": 1,
			"submit": 1,
			"cancel": 1,
			"amend": 1,
			"report": 1,
		},
	],
	"PM Opening Advance": [
		{
			"role": "System Manager",
			"read": 1,
			"write": 1,
			"create": 1,
			"delete": 1,
			"submit": 1,
			"cancel": 1,
			"amend": 1,
			"report": 1,
			"export": 1,
			"print": 1,
			"email": 1,
			"share": 1,
		},
		{
			"role": "Petty Management Accountant",
			"read": 1,
			"write": 1,
			"create": 1,
			"submit": 1,
			"cancel": 1,
			"amend": 1,
			"delete": 1,
			"report": 1,
		},
	],
	"PM Settings": [
		{"role": "System Manager", "read": 1, "write": 1, "create": 1},
		{"role": "Petty Management Accountant", "read": 1, "write": 1},
	],
	"PM Holder": [
		{
			"role": "System Manager",
			"read": 1,
			"write": 1,
			"create": 1,
			"delete": 1,
			"report": 1,
			"export": 1,
			"print": 1,
			"email": 1,
			"share": 1,
		},
		{
			"role": "Petty Management Accountant",
			"read": 1,
			"write": 1,
			"create": 1,
			"delete": 1,
			"report": 1,
		},
		{"role": "Petty Management User", "read": 1, "report": 1},
	],
}

REPORT_ROLES = {
	"PM Balance Report": ("System Manager", "Petty Management Accountant", "Petty Management User"),
	"PM Funding History": ("System Manager", "Petty Management Accountant"),
	"PM Opening Advance Availability Report": ("System Manager", "Petty Management Accountant"),
	"PM Pending Clearance Report": ("System Manager", "Petty Management Accountant"),
	"PM Ledger Report": ("System Manager", "Petty Management Accountant"),
	"PM Settlement Ledger": ("System Manager", "Petty Management Accountant"),
	"PM Request Availability Report": ("System Manager", "Petty Management Accountant"),
}


def _mark_roles_deprecated() -> None:
	for role in DEPRECATED_PM_ROLES:
		if not frappe.db.exists("Role", role):
			continue
		# Keep role for one release (users may still hold Has Role). Do not disable —
		# disabling breaks sites mid-migration. Annotate via desk_access preserved.
		# Soft deprecation: store flag in Role description when field exists.
		try:
			meta = frappe.get_meta("Role")
			if meta.has_field("desk_access"):
				# leave desk_access as-is so legacy assignments still work during deprecation window
				pass
			frappe.db.set_value(
				"Role",
				role,
				"disabled",
				0,
				update_modified=False,
			)
		except Exception:
			pass


def _sync_doctype_perms(doctype: str, rows: list[dict]) -> None:
	"""Replace DocPerm rows without full DocType.validate (search_fields etc.)."""
	if not frappe.db.exists("DocType", doctype):
		return

	frappe.db.delete("DocPerm", {"parent": doctype})
	for idx, row in enumerate(rows, start=1):
		perm = {
			"name": frappe.generate_hash(length=10),
			"parent": doctype,
			"parenttype": "DocType",
			"parentfield": "permissions",
			"idx": idx,
			"permlevel": row.get("permlevel", 0),
			"role": row["role"],
			"read": int(row.get("read") or 0),
			"write": int(row.get("write") or 0),
			"create": int(row.get("create") or 0),
			"delete": int(row.get("delete") or 0),
			"submit": int(row.get("submit") or 0),
			"cancel": int(row.get("cancel") or 0),
			"amend": int(row.get("amend") or 0),
			"report": int(row.get("report") or 0),
			"export": int(row.get("export") or 0),
			"import": int(row.get("import") or 0),
			"share": int(row.get("share") or 0),
			"print": int(row.get("print") or 0),
			"email": int(row.get("email") or 0),
			"if_owner": int(row.get("if_owner") or 0),
			"select": int(row.get("select") or 0),
		}
		frappe.get_doc({"doctype": "DocPerm", **perm}).db_insert()

	if frappe.db.exists("DocType", "Custom DocPerm"):
		frappe.db.delete(
			"Custom DocPerm",
			{"parent": doctype, "role": ("in", list(DEPRECATED_PM_ROLES))},
		)

	frappe.clear_cache(doctype=doctype)
	try:
		from frappe.core.doctype.doctype.doctype import clear_permissions_cache

		clear_permissions_cache(doctype)
	except Exception:
		pass


def _sync_report_roles() -> None:
	for report, roles in REPORT_ROLES.items():
		if not frappe.db.exists("Report", report):
			continue
		frappe.db.delete("Has Role", {"parent": report, "parenttype": "Report"})
		for idx, role in enumerate(roles, start=1):
			frappe.get_doc(
				{
					"doctype": "Has Role",
					"parent": report,
					"parenttype": "Report",
					"parentfield": "roles",
					"idx": idx,
					"role": role,
				}
			).db_insert()
		frappe.clear_cache(doctype="Report")


def execute():
	_mark_roles_deprecated()
	_rebuild_pm_request_workflow()
	_rebuild_pm_clearance_workflow()
	_seed_assignment_rules()

	for doctype, rows in DOCTYPE_PERMS.items():
		_sync_doctype_perms(doctype, rows)
	_sync_report_roles()

	frappe.clear_cache()
	frappe.db.commit()
	frappe.logger("erpnext_extensions").info(
		"migrate_pm_roles_autoskip_v414: workflows rebuilt; DocPerm collapsed to User/Accountant/System Manager"
	)
