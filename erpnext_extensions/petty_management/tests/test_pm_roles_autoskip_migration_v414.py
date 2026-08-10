# Copyright (c) 2026, ERPNext Extensions contributors
"""v4.1.4 migration: legacy Manager → User grant + DocPerm hardening (idempotent)."""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from erpnext_extensions.patches.post_model_sync.migrate_pm_roles_autoskip_v414 import (
	DOCTYPE_PERMS,
	grant_pm_user_to_legacy_managers,
	execute as migrate_v414,
)


def _ensure_role(role: str) -> None:
	if not frappe.db.exists("Role", role):
		frappe.get_doc({"doctype": "Role", "role_name": role}).insert(ignore_permissions=True)


def _user_has_role(user: str, role: str) -> bool:
	return bool(frappe.db.exists("Has Role", {"parent": user, "role": role, "parenttype": "User"}))


def _make_user(email: str, roles: list[str], *, enabled: int = 1) -> str:
	for role in roles:
		_ensure_role(role)
	if frappe.db.exists("User", email):
		frappe.delete_doc("User", email, force=True, ignore_permissions=True)
		frappe.db.commit()
	u = frappe.get_doc(
		{
			"doctype": "User",
			"email": email,
			"first_name": email.split("@")[0][:30],
			"send_welcome_email": 0,
			"user_type": "System User",
			"enabled": enabled,
		}
	)
	u.insert(ignore_permissions=True)
	for role in roles:
		u.append("roles", {"role": role})
	u.enabled = enabled
	u.save(ignore_permissions=True)
	frappe.db.commit()
	return email


class TestPMRolesAutoskipMigrationV414(FrappeTestCase):
	def tearDown(self):
		frappe.set_user("Administrator")
		for email in (
			"pm_mig_mgr_only@example.com",
			"pm_mig_mgr_user@example.com",
			"pm_mig_mgr_disabled@example.com",
		):
			if frappe.db.exists("User", email):
				frappe.delete_doc("User", email, force=True, ignore_permissions=True)
		frappe.db.commit()

	def test_manager_only_receives_user(self):
		email = _make_user("pm_mig_mgr_only@example.com", ["Petty Management Manager"])
		self.assertFalse(_user_has_role(email, "Petty Management User"))
		stats = grant_pm_user_to_legacy_managers()
		self.assertTrue(_user_has_role(email, "Petty Management User"))
		self.assertTrue(_user_has_role(email, "Petty Management Manager"))
		self.assertGreaterEqual(stats["granted"], 1)

	def test_manager_plus_user_no_duplicate(self):
		email = _make_user(
			"pm_mig_mgr_user@example.com",
			["Petty Management Manager", "Petty Management User"],
		)
		before = frappe.db.count(
			"Has Role", {"parent": email, "role": "Petty Management User", "parenttype": "User"}
		)
		stats = grant_pm_user_to_legacy_managers()
		after = frappe.db.count(
			"Has Role", {"parent": email, "role": "Petty Management User", "parenttype": "User"}
		)
		self.assertEqual(before, 1)
		self.assertEqual(after, 1)
		self.assertGreaterEqual(stats["already_had_user"], 1)

	def test_disabled_manager_skipped(self):
		email = _make_user(
			"pm_mig_mgr_disabled@example.com",
			["Petty Management Manager"],
			enabled=0,
		)
		stats = grant_pm_user_to_legacy_managers()
		self.assertFalse(_user_has_role(email, "Petty Management User"))
		self.assertGreaterEqual(stats["disabled_skipped"], 1)

	def test_second_run_is_idempotent(self):
		email = _make_user("pm_mig_mgr_only@example.com", ["Petty Management Manager"])
		first = grant_pm_user_to_legacy_managers()
		self.assertTrue(_user_has_role(email, "Petty Management User"))
		second = grant_pm_user_to_legacy_managers()
		self.assertEqual(second["granted"], 0)
		count = frappe.db.count(
			"Has Role", {"parent": email, "role": "Petty Management User", "parenttype": "User"}
		)
		self.assertEqual(count, 1)
		self.assertGreaterEqual(first["granted"], 1)

	def test_accountant_delete_stripped_after_migrate(self):
		migrate_v414()
		for doctype, rows in DOCTYPE_PERMS.items():
			if doctype in ("PM Settings",):
				continue
			db_rows = frappe.get_all(
				"DocPerm",
				filters={"parent": doctype, "role": "Petty Management Accountant"},
				fields=["delete", "cancel", "submit"],
			)
			if not db_rows:
				continue
			for row in db_rows:
				self.assertEqual(int(row.delete or 0), 0, msg=doctype)
			sm = frappe.get_all(
				"DocPerm",
				filters={"parent": doctype, "role": "System Manager"},
				fields=["delete"],
			)
			if doctype in ("PM Request", "PM Clearance", "PM Opening Advance", "PM Holder"):
				self.assertTrue(sm and int(sm[0].delete or 0) == 1, msg=doctype)
