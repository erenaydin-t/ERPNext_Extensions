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

LEGACY_MANAGER_ROLE = "Petty Management Manager"
PM_USER_ROLE = "Petty Management User"

# DocPerm targets after role collapse (JSON + Custom DocPerm sync).
# Accountant MUST NOT have delete on transactional/financial PM doctypes.
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
			"report": 1,
			# delete intentionally omitted — break-glass via System Manager only
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
			"report": 1,
			# delete omitted — master-data delete is System Manager only
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
		# Keep role enabled for one release (Has Role / visibility-role picker).
		try:
			frappe.db.set_value("Role", role, "disabled", 0, update_modified=False)
		except Exception:
			pass


def grant_pm_user_to_legacy_managers() -> dict:
	"""Ensure every enabled user with Petty Management Manager also has Petty Management User.

	Idempotent. Does not remove Manager. Skips disabled users. Does not touch Admin/Auditor
	(those roles had no Manager/CEO workflow Allowed Role; Admin cancel/delete moved to
	System Manager / Accountant cancel without auto-granting Accountant).
	"""
	stats = {"scanned": 0, "granted": 0, "already_had_user": 0, "disabled_skipped": 0}
	if not frappe.db.exists("Role", LEGACY_MANAGER_ROLE):
		return stats
	if not frappe.db.exists("Role", PM_USER_ROLE):
		frappe.get_doc({"doctype": "Role", "role_name": PM_USER_ROLE}).insert(ignore_permissions=True)

	manager_users = frappe.get_all(
		"Has Role",
		filters={"role": LEGACY_MANAGER_ROLE, "parenttype": "User"},
		pluck="parent",
	)
	for user in manager_users:
		stats["scanned"] += 1
		if not frappe.db.exists("User", user):
			continue
		enabled = frappe.db.get_value("User", user, "enabled")
		if not enabled:
			stats["disabled_skipped"] += 1
			continue
		has_user = frappe.db.exists("Has Role", {"parent": user, "role": PM_USER_ROLE, "parenttype": "User"})
		if has_user:
			stats["already_had_user"] += 1
			continue
		doc = frappe.get_doc("User", user)
		doc.append("roles", {"role": PM_USER_ROLE})
		doc.save(ignore_permissions=True)
		stats["granted"] += 1
	return stats


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

	# Strip Custom DocPerm for deprecated roles and any Accountant delete overrides.
	if frappe.db.exists("DocType", "Custom DocPerm"):
		frappe.db.delete(
			"Custom DocPerm",
			{"parent": doctype, "role": ("in", list(DEPRECATED_PM_ROLES))},
		)
		if doctype in ("PM Request", "PM Clearance", "PM Opening Advance", "PM Holder"):
			frappe.db.sql(
				"""
				UPDATE `tabCustom DocPerm`
				SET `delete` = 0
				WHERE parent = %s AND role = %s AND `delete` = 1
				""",
				(doctype, "Petty Management Accountant"),
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
	grant_stats = grant_pm_user_to_legacy_managers()
	_rebuild_pm_request_workflow()
	_rebuild_pm_clearance_workflow()
	_seed_assignment_rules()

	for doctype, rows in DOCTYPE_PERMS.items():
		_sync_doctype_perms(doctype, rows)
	_sync_report_roles()

	frappe.clear_cache()
	frappe.db.commit()
	frappe.logger("erpnext_extensions").info(
		f"migrate_pm_roles_autoskip_v414: workflows rebuilt; DocPerm synced; "
		f"legacy Manager→User grants={grant_stats}"
	)
