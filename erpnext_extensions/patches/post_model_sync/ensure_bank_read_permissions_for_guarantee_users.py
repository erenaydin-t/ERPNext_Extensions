# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT
"""Additive Bank read/select for Accounts User and Accounts Manager (Guarantee Document).

Idempotent and non-destructive:
- only adds missing read/select
- never removes or reduces existing permissions
- never grants create/write/delete
"""

from __future__ import annotations

import frappe
from frappe.permissions import add_permission, setup_custom_perms, update_permission_property
from frappe.utils import cint

ROLES = ("Accounts User", "Accounts Manager")
DOCTYPE = "Bank"


def execute() -> None:
	if not frappe.db.exists("DocType", DOCTYPE):
		return

	for role in ROLES:
		_ensure_read_select(DOCTYPE, role)

	frappe.clear_cache(doctype=DOCTYPE)


def _ensure_read_select(doctype: str, role: str) -> None:
	# Ensure Custom DocPerm table is seeded from DocPerm when empty (copy only).
	setup_custom_perms(doctype)

	rows = frappe.db.sql(
		"""
		SELECT name, `read`, `select`
		FROM `tabCustom DocPerm`
		WHERE parent=%s AND role=%s AND permlevel=0 AND ifnull(if_owner, 0)=0
		LIMIT 1
		""",
		(doctype, role),
		as_dict=True,
	)
	existing = rows[0] if rows else None

	if not existing:
		# Creates a new Custom DocPerm row with read=1 only.
		add_permission(doctype, role, permlevel=0, ptype="read")
		update_permission_property(doctype, role, 0, "select", 1)
		return

	# Additive only — never clear other flags.
	if not cint(existing.get("read")):
		update_permission_property(doctype, role, 0, "read", 1)
	if not cint(existing.get("select")):
		update_permission_property(doctype, role, 0, "select", 1)
