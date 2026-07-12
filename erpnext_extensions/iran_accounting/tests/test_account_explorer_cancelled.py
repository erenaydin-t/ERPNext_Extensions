# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

import json
import unittest

import frappe

from erpnext_extensions.iran_accounting.account_explorer import api
from erpnext_extensions.iran_accounting.tests.test_account_explorer_fixtures import (
	current_fiscal_year,
	enable_account_explorer,
	require_site,
)


class TestAccountExplorerCancelled(unittest.TestCase):
	def setUp(self):
		self.company = require_site(self)
		enable_account_explorer()
		frappe.set_user("Administrator")
		fy = current_fiscal_year(self.company)
		if not fy:
			self.skipTest("No fiscal year")
		self.fiscal_year, self.from_date, self.to_date = fy

	def test_default_excludes_cancelled_from_active_totals(self):
		payload = json.dumps(
			{
				"document_scope": {
					"company": self.company,
					"fiscal_year": self.fiscal_year,
					"from_date": self.from_date,
					"to_date": self.to_date,
					"include_cancelled_entries": 0,
				}
			}
		)
		result = api.get_account_summary(payload)
		self.assertNotIn("cancelled_section", result)

	def test_include_cancelled_flag_accepted(self):
		payload = json.dumps(
			{
				"document_scope": {
					"company": self.company,
					"fiscal_year": self.fiscal_year,
					"from_date": self.from_date,
					"to_date": self.to_date,
					"include_cancelled_entries": 1,
				}
			}
		)
		result = api.get_account_summary(payload)
		self.assertIn("totals", result)
