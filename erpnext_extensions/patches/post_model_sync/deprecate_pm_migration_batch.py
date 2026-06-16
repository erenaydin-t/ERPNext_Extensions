"""Hide migration_batch on PM Opening Advance; re-sync desk without PM Migration Batch."""

from __future__ import annotations

import frappe


def execute():
	if frappe.db.has_column("PM Opening Advance", "migration_batch"):
		frappe.db.sql(
			"""
			update `tabCustom Field`
			set hidden = 1, reqd = 0
			where dt = 'PM Opening Advance' and fieldname = 'migration_batch'
			"""
		)
		frappe.db.sql(
			"""
			update `tabDocField`
			set hidden = 1, reqd = 0
			where parent = 'PM Opening Advance' and fieldname = 'migration_batch'
			"""
		)
	frappe.clear_cache(doctype="PM Opening Advance")

	from erpnext_extensions.patches.post_model_sync.add_petty_management_workspace import (
		execute as sync_petty_management_workspace,
	)

	sync_petty_management_workspace()
