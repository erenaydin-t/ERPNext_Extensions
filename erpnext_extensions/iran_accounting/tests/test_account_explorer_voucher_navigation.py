# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

import json
import unittest

import frappe

from erpnext_extensions.iran_accounting.account_explorer import api
from erpnext_extensions.iran_accounting.tests.test_account_explorer_fixtures import (
	current_fiscal_year,
	enable_wave2b_voucher,
	require_site,
)


class TestAccountExplorerVoucherNavigation(unittest.TestCase):
	def setUp(self):
		self.company = require_site(self)
		enable_wave2b_voucher()
		frappe.set_user("Administrator")
		fy = current_fiscal_year(self.company)
		if not fy:
			self.skipTest("No fiscal year")
		self.fiscal_year, self.from_date, self.to_date = fy
		self.sample = frappe.db.get_value(
			"GL Entry",
			{"company": self.company, "is_cancelled": 0},
			["voucher_type", "voucher_no"],
			as_dict=True,
		)
		if not self.sample:
			self.skipTest("No GL Entry data")

	def _payload(self):
		return json.dumps(
			{
				"document_scope": {
					"company": self.company,
					"fiscal_year": self.fiscal_year,
					"from_date": self.from_date,
					"to_date": self.to_date,
				},
				"analysis_context": {
					"voucher_scope": {
						"voucher_type": self.sample.voucher_type,
						"voucher_no": self.sample.voucher_no,
					}
				},
			}
		)

	def test_navigation_target_structure(self):
		result = api.get_voucher_navigation_target(self._payload())
		self.assertEqual(result["voucher_type"], self.sample.voucher_type)
		self.assertEqual(result["voucher_no"], self.sample.voucher_no)
		self.assertIn("can_open_gl_list", result)
		self.assertIn("can_open_source", result)

	def test_navigation_disabled_when_setting_off(self):
		settings = frappe.get_single("Iran Accounting Settings")
		settings.allow_gl_entry_navigation = 0
		settings.flags.ignore_permissions = True
		settings.save()
		frappe.db.commit()

		result = api.get_voucher_navigation_target(self._payload())
		self.assertFalse(result["can_open_gl_list"])
		self.assertFalse(result["can_open_source"])
