# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

import unittest
from unittest.mock import patch

import frappe

from erpnext_extensions.iran_accounting.account_explorer import diagnostics
from erpnext_extensions.iran_accounting.account_explorer import api
from erpnext_extensions.iran_accounting.tests.test_account_explorer_fixtures import (
	current_fiscal_year,
	disable_diagnostics,
	enable_account_explorer,
	enable_diagnostics,
	enable_wave2a_analysis,
	enable_wave2b_voucher,
	require_site,
)


class TestAccountExplorerDiagnostics(unittest.TestCase):
	def setUp(self):
		self.company = require_site(self)
		enable_wave2a_analysis()
		enable_wave2b_voucher(include_wave2a=False)
		enable_diagnostics()
		frappe.set_user("Administrator")

	def tearDown(self):
		frappe.set_user("Administrator")
		enable_diagnostics()

	def test_diagnostics_disabled_blocks_api(self):
		disable_diagnostics()
		with self.assertRaises(frappe.ValidationError):
			diagnostics.run_account_explorer_diagnostics(self.company)
		enable_diagnostics()

	def test_accounts_user_denied(self):
		with patch(
			"erpnext_extensions.iran_accounting.account_explorer.diagnostics.assert_diagnostics_allowed",
			side_effect=frappe.PermissionError("Not permitted"),
		):
			with self.assertRaises(frappe.PermissionError):
				diagnostics.run_account_explorer_diagnostics(self.company)

	def test_diagnostics_report_structure(self):
		result = diagnostics.run_account_explorer_diagnostics(self.company)
		self.assertEqual(result["company"], self.company)
		self.assertEqual(result["read_only"], 1)
		self.assertIn("findings", result)
		self.assertIn("summary", result)
		categories = {row["category"] for row in result["findings"]}
		self.assertTrue({"accounts", "dimensions", "party", "currency"}.issubset(categories))

	def test_account_duplicate_code_detection(self):
		accounts = frappe.get_all(
			"Account",
			filters={"company": self.company, "is_group": 0},
			fields=["name", "account_number"],
			limit=2,
		)
		if len(accounts) < 2:
			self.skipTest("Need at least two leaf accounts")
		original_numbers = {row.name: row.account_number for row in accounts}
		test_number = "999888777"
		frappe.db.set_value("Account", accounts[0].name, "account_number", test_number)
		frappe.db.set_value("Account", accounts[1].name, "account_number", test_number)
		frappe.db.commit()
		try:
			findings = diagnostics.run_account_diagnostics(self.company)
			duplicate = next(row for row in findings if row["check_id"] == "duplicate_account_codes")
			self.assertGreater(duplicate["count"], 0)
		finally:
			for name, number in original_numbers.items():
				frappe.db.set_value("Account", name, "account_number", number)
			frappe.db.commit()

	def test_metadata_includes_diagnostics_flag(self):
		meta = api.get_metadata()
		self.assertIn("diagnostics_enabled", meta)
		self.assertEqual(meta.get("diagnostics_enabled"), 1)

	def test_company_permission(self):
		with patch(
			"erpnext_extensions.iran_accounting.account_explorer.diagnostics.assert_company_allowed",
			side_effect=frappe.PermissionError("Not permitted for company"),
		):
			with self.assertRaises(frappe.PermissionError):
				diagnostics.run_account_explorer_diagnostics(self.company)

	def test_whitelisted_diagnostics_entry_point(self):
		from erpnext_extensions.iran_accounting.account_explorer import get_account_explorer_diagnostics

		result = get_account_explorer_diagnostics(self.company)
		self.assertEqual(result["company"], self.company)

	def test_read_only_no_mutations(self):
		before_accounts = frappe.db.count("Account", {"company": self.company})
		before_gl = frappe.db.count("GL Entry", {"company": self.company})
		diagnostics.run_account_explorer_diagnostics(self.company)
		self.assertEqual(frappe.db.count("Account", {"company": self.company}), before_accounts)
		self.assertEqual(frappe.db.count("GL Entry", {"company": self.company}), before_gl)


class TestAccountExplorerDiagnosticsAccess(unittest.TestCase):
	def setUp(self):
		self.company = require_site(self)
		enable_account_explorer()
		enable_diagnostics()

	def test_page_exists(self):
		self.assertTrue(frappe.db.exists("Page", "account-explorer-diagnostics"))

	def test_page_roles_accounts_manager_only(self):
		doc = frappe.get_doc("Page", "account-explorer-diagnostics")
		roles = [row.role for row in doc.roles]
		self.assertIn("Accounts Manager", roles)
		self.assertNotIn("Accounts User", roles)
