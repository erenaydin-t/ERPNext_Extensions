# Copyright (c) 2026, Farbod Siyahpoosh and contributors
"""Deterministic users for PM Request API security tests and E2E."""

from __future__ import annotations

import frappe
from frappe.utils import now
from frappe.utils.password import update_password


def _insert_user_row(email: str, first_name: str, last_name: str) -> str:
	if frappe.db.exists("User", email):
		frappe.delete_doc("User", email, force=True, ignore_permissions=True)
	cols = set(frappe.db.get_table_columns("User"))
	now_ts = now()
	candidate = {
		"name": email,
		"email": email,
		"enabled": 1,
		"first_name": first_name,
		"last_name": last_name,
		"full_name": f"{first_name} {last_name}".strip(),
		"user_type": "System User",
		"send_welcome_email": 0,
		"creation": now_ts,
		"modified": now_ts,
		"owner": "Administrator",
		"modified_by": "Administrator",
		"docstatus": 0,
		"idx": 0,
	}
	row = {k: v for k, v in candidate.items() if k in cols}
	field_names = list(row.keys())
	placeholders = ", ".join(["%s"] * len(field_names))
	col_sql = ", ".join(f"`{f}`" for f in field_names)
	frappe.db.sql(
		f"INSERT INTO `tabUser` ({col_sql}) VALUES ({placeholders})",
		tuple(row[f] for f in field_names),
	)
	update_password(email, "pm_sec_test_1")
	return email


def _append_user_role(user: str, role: str) -> None:
	frappe.get_doc(
		{
			"doctype": "Has Role",
			"parent": user,
			"parenttype": "User",
			"parentfield": "roles",
			"role": role,
		}
	).insert(ignore_permissions=True)


def petty_management_user_with_company_only(company: str, *, tag: str = "sec") -> str:
	email = f"pm_{tag}_{frappe.generate_hash(length=10)}@example.com"
	_insert_user_row(email, "PM", "SecurityTest")
	_append_user_role(email, "Petty Management User")
	perm = frappe.new_doc("User Permission")
	perm.user = email
	perm.allow = "Company"
	perm.for_value = company
	perm.apply_to_all_doctypes = 1
	perm.flags.ignore_permissions = True
	perm.insert()
	frappe.db.commit()
	return email


def non_pm_user_for_read_denial(*, tag: str = "nopm") -> str:
	email = f"pm_{tag}_{frappe.generate_hash(length=10)}@example.com"
	_insert_user_row(email, "No", "PMRole")
	_append_user_role(email, "Employee")
	frappe.db.commit()
	return email


def delete_user_if_exists(email: str) -> None:
	if email and frappe.db.exists("User", email):
		frappe.delete_doc("User", email, force=True, ignore_permissions=True)
		frappe.db.commit()
