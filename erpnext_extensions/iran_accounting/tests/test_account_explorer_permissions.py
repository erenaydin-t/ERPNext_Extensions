# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

import json
import unittest

import frappe

from erpnext_extensions.iran_accounting.account_explorer import api
from erpnext_extensions.iran_accounting.tests.test_account_explorer_fixtures import (
	current_fiscal_year,
	disable_account_explorer,
	enable_account_explorer,
	require_site,
)


class TestAccountExplorerPermissions(unittest.TestCase):
	def setUp(self):
		self.company = require_site(self)
		frappe.set_user("Administrator")

	def test_feature_disabled_blocks_summary(self):
		disable_account_explorer()
		fy = current_fiscal_year(self.company)
		if not fy:
			self.skipTest("No fiscal year")
		payload = json.dumps(
			{
				"document_scope": {
					"company": self.company,
					"fiscal_year": fy[0],
					"from_date": fy[1],
					"to_date": fy[2],
				}
			}
		)
		with self.assertRaises(frappe.ValidationError):
			api.get_account_summary(payload)
		enable_account_explorer()

	def test_metadata_available_when_disabled(self):
		disable_account_explorer()
		meta = api.get_metadata()
		self.assertEqual(meta.get("enabled"), 0)
		enable_account_explorer()

	def test_iran_accounting_settings_system_manager_has_write(self):
		"""System Manager must be able to edit the Single (Prod read-only root cause)."""
		from frappe.permissions import get_role_permissions, has_permission

		meta = frappe.get_meta("Iran Accounting Settings")
		rows = {
			r.role: r
			for r in frappe.get_all(
				"DocPerm",
				filters={"parent": "Iran Accounting Settings", "permlevel": 0},
				fields=["role", "read", "write", "create", "delete", "print", "email", "share"],
			)
		}
		self.assertIn("System Manager", rows)
		sm = rows["System Manager"]
		for right in ("read", "write", "create", "delete", "print", "email", "share"):
			self.assertEqual(int(sm.get(right) or 0), 1, right)

		# Accounts User remains read-only (no write)
		self.assertIn("Accounts User", rows)
		self.assertEqual(int(rows["Accounts User"].write or 0), 0)

		# Role evaluation: System Manager alone gets write
		orig = frappe.get_roles
		try:
			frappe.get_roles = lambda user=None: ["System Manager", "All", "Desk User"]
			frappe.local.role_permissions = {}
			perms = get_role_permissions(meta, user="sm@perm.test")
			self.assertEqual(int(perms.get("read") or 0), 1)
			self.assertEqual(int(perms.get("write") or 0), 1)
			self.assertTrue(has_permission("Iran Accounting Settings", "write", user="sm@perm.test"))
			self.assertTrue(has_permission("Iran Accounting Settings", "read", user="sm@perm.test"))
		finally:
			frappe.get_roles = orig
			frappe.local.role_permissions = {}
