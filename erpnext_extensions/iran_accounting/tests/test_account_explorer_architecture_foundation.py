"""Wave 3B-0 architecture foundation guards."""

from __future__ import annotations

import os
import unittest

import frappe


class TestAccountExplorerArchitectureFoundation(unittest.TestCase):
	def setUp(self):
		self.app_root = frappe.get_app_path("erpnext_extensions")

	def test_adr_documents_exist(self):
		for name in (
			"ADR-3B-001-datatable.md",
			"ADR-3B-002-workspace-url.md",
			"ADR-3B-003-page-lifecycle.md",
		):
			path = os.path.join(self.app_root, "iran_accounting", "docs", "adr", name)
			self.assertTrue(os.path.isfile(path), f"missing ADR: {name}")

	def test_core_modules_exist(self):
		base = os.path.join(
			self.app_root,
			"erpnext_extensions",
			"page",
			"account_explorer",
		)
		for rel in (
			"core/explorer_events.js",
			"core/explorer_store.js",
			"core/explorer_plugins.js",
			"core/explorer_workspace_state.js",
			"adapters/ae_datatable_adapter.js",
		):
			path = os.path.join(base, rel)
			self.assertTrue(os.path.isfile(path), f"missing module: {rel}")

	def test_page_entry_includes_core_modules(self):
		page_js = os.path.join(
			self.app_root,
			"erpnext_extensions",
			"page",
			"account_explorer",
			"account_explorer.js",
		)
		with open(page_js, encoding="utf-8") as handle:
			content = handle.read()
		for fragment in (
			'{% include "erpnext_extensions/erpnext_extensions/page/account_explorer/core/explorer_events.js" %}',
			'{% include "erpnext_extensions/erpnext_extensions/page/account_explorer/adapters/ae_datatable_adapter.js" %}',
			'$(wrapper).bind("show"',
			"_init_explorer_architecture",
		):
			self.assertIn(fragment, content, f"missing entry hook: {fragment}")

	def test_page_registration_unchanged(self):
		page = frappe.get_doc("Page", "account-explorer")
		self.assertEqual(page.module, "erpnext_extensions")
		self.assertEqual(page.page_name, "account-explorer")
