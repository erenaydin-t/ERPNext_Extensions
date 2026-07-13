"""Seed default Account Explorer levels when settings table is empty (idempotent)."""

from __future__ import annotations

import frappe

from erpnext_extensions.iran_accounting.account_explorer.constants import DEFAULT_LEVELS


def execute():
	if not frappe.db.exists("DocType", "Iran Accounting Settings"):
		return

	settings = frappe.get_single("Iran Accounting Settings")
	if settings.account_explorer_levels:
		return

	for row in DEFAULT_LEVELS:
		settings.append(
			"account_explorer_levels",
			{
				"sequence": row["sequence"],
				"enabled": row["enabled"],
				"code_length": row["code_length"],
				"title": row["title"],
				"title_fa": row["title_fa"],
				"drill_down_enabled": 1,
				"default_visible": 1,
				"default_sort_order": "code",
			},
		)

	settings.flags.ignore_permissions = True
	settings.save()
