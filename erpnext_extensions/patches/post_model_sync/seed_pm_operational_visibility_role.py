# Copyright (c) 2026, ERPNext Extensions contributors
"""v4.1.3: seed PM Settings.operational_pm_visibility_role (idempotent)."""

from __future__ import annotations

import frappe

DEFAULT_ROLE = "Petty Management Accountant"


def execute():
	if not frappe.db.exists("DocType", "PM Settings"):
		return

	# Singles store values in tabSingles — do not use has_column / tabPM Settings.
	meta = frappe.get_meta("PM Settings")
	if not meta.has_field("operational_pm_visibility_role"):
		return

	if not frappe.db.exists("Role", DEFAULT_ROLE):
		frappe.get_doc({"doctype": "Role", "role_name": DEFAULT_ROLE}).insert(ignore_permissions=True)

	current = frappe.db.get_single_value("PM Settings", "operational_pm_visibility_role")
	if current:
		return

	frappe.db.set_single_value("PM Settings", "operational_pm_visibility_role", DEFAULT_ROLE)
