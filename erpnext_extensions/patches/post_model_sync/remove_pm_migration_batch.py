"""Remove PM Migration Batch DocType and migration_batch column from PM Opening Advance."""

from __future__ import annotations

import frappe


def execute():
	if frappe.db.has_column("PM Opening Advance", "migration_batch"):
		frappe.db.sql(
			"""
			UPDATE `tabPM Opening Advance`
			SET migration_batch = NULL
			WHERE IFNULL(migration_batch, '') != ''
			"""
		)
		frappe.db.sql(
			"""
			DELETE FROM `tabDocField`
			WHERE parent = 'PM Opening Advance' AND fieldname = 'migration_batch'
			"""
		)
		frappe.db.sql(
			"""
			DELETE FROM `tabCustom Field`
			WHERE dt = 'PM Opening Advance' AND fieldname = 'migration_batch'
			"""
		)
		try:
			frappe.db.sql_ddl("ALTER TABLE `tabPM Opening Advance` DROP COLUMN migration_batch")
		except Exception:
			frappe.log_error(frappe.get_traceback(), "pm_opening_advance_drop_migration_batch")

	if frappe.db.exists("DocType", "PM Migration Batch"):
		try:
			frappe.delete_doc("DocType", "PM Migration Batch", force=True, ignore_missing=True)
		except Exception:
			frappe.log_error(frappe.get_traceback(), "pm_migration_batch_doctype_delete")

	frappe.clear_cache(doctype="PM Opening Advance")

	from erpnext_extensions.patches.post_model_sync.add_petty_management_workspace import (
		execute as sync_petty_management_workspace,
	)

	sync_petty_management_workspace()
