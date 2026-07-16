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
		self.assertFalse(result["can_print"])

	def test_print_navigation_requires_print_format(self):
		settings = frappe.get_single("Iran Accounting Settings")
		settings.show_print_voucher = 1
		settings.account_explorer_voucher_print_format = None
		settings.flags.ignore_permissions = True
		settings.save()
		frappe.db.commit()

		result = api.get_voucher_navigation_target(self._payload())
		self.assertIn("can_print", result)
		self.assertIn("print_format", result)
		self.assertFalse(result["can_print"])
		self.assertIsNone(result.get("print_route"))

		# Use Voucher GL Print Standard only as a named Print Format that exists;
		# source voucher print needs a DocType print format — skip if none for voucher.
		sample_pf = frappe.db.get_value(
			"Print Format",
			{"doc_type": self.sample.voucher_type, "disabled": 0},
			"name",
		)
		if not sample_pf:
			self.skipTest(f"No Print Format for {self.sample.voucher_type}")
		settings.account_explorer_voucher_print_format = sample_pf
		settings.flags.ignore_permissions = True
		settings.save()
		frappe.db.commit()

		result = api.get_voucher_navigation_target(self._payload())
		if result["can_open_source"]:
			self.assertTrue(result["can_print"])
			self.assertEqual(result["print_format"], sample_pf)
			self.assertEqual(result["print_route"]["format"], sample_pf)
			self.assertEqual(result["print_route"]["doctype"], self.sample.voucher_type)
			self.assertEqual(result["print_route"]["name"], self.sample.voucher_no)
		self.assertIn("can_print_gl", result)
