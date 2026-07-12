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
