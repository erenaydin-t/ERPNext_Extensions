# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

import unittest

import frappe

from erpnext_extensions.iran_accounting.account_explorer import api
from erpnext_extensions.iran_accounting.tests.test_account_explorer_fixtures import (
	enable_wave2c_unified_party,
	require_site,
)


class TestAccountExplorerUnifiedPartySuggestions(unittest.TestCase):
	def setUp(self):
		self.company = require_site(self)
		enable_wave2c_unified_party()
		frappe.set_user("Administrator")

	def test_suggestions_are_read_only(self):
		before = frappe.db.count("Unified Accounting Party")
		result = api.get_unified_party_suggestions({"company": self.company, "limit": 10})
		after = frappe.db.count("Unified Accounting Party")
		self.assertEqual(before, after)
		self.assertIn("suggestions", result)
		self.assertIn("warnings", result)
		for suggestion in result["suggestions"]:
			self.assertIn("members", suggestion)
			self.assertGreaterEqual(len(suggestion["members"]), 2)

	def test_suggestions_blocked_when_disabled(self):
		settings = frappe.get_single("Iran Accounting Settings")
		settings.unified_party_enabled = 0
		settings.flags.ignore_permissions = True
		settings.save()
		frappe.db.commit()
		with self.assertRaises(frappe.ValidationError):
			api.get_unified_party_suggestions({"company": self.company})
