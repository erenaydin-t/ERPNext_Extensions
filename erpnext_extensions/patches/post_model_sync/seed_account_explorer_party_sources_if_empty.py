"""Seed default Account Explorer party sources when configuration is empty (idempotent)."""

from __future__ import annotations

import frappe

from erpnext_extensions.iran_accounting.account_explorer.constants import DEFAULT_PARTY_SOURCES


def execute():
	if not frappe.db.exists("DocType", "Iran Accounting Settings"):
		return

	settings = frappe.get_single("Iran Accounting Settings")
	if settings.account_explorer_party_sources:
		return

	for row in DEFAULT_PARTY_SOURCES:
		settings.append(
			"account_explorer_party_sources",
			{
				"sequence": row["sequence"],
				"enabled": row["enabled"],
				"party_type": row["party_type"],
				"label": row["label"],
				"label_fa": row.get("label_fa"),
				"show_in_unified_party": 0,
			},
		)

	settings.flags.ignore_permissions = True
	settings.save()
