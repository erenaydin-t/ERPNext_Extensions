# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

import json
import unittest

import frappe
from frappe.utils import getdate

from erpnext_extensions.iran_accounting.account_explorer.account_hierarchy import (
	normalize_account_number,
)
from erpnext_extensions.iran_accounting.account_explorer.query_spec import (
	AccountExplorerQuerySpec_from_client,
)
from erpnext_extensions.iran_accounting.tests.test_account_explorer_fixtures import (
	current_fiscal_year,
	enable_account_explorer,
	require_site,
)


class TestAccountExplorerQuerySpec(unittest.TestCase):
	def setUp(self):
		self.company = require_site(self)
		enable_account_explorer()
		frappe.set_user("Administrator")

	def test_requires_company(self):
		with self.assertRaises(frappe.ValidationError):
			AccountExplorerQuerySpec_from_client(json.dumps({"document_scope": {}}))

	def test_requires_dates(self):
		company_without_fy = "_Test Company 2"
		if not frappe.db.exists("Company", company_without_fy):
			self.skipTest("Fallback company not available")
		if current_fiscal_year(company_without_fy):
			self.skipTest("Fallback company has fiscal year auto-resolution")
		with self.assertRaises(frappe.ValidationError):
			AccountExplorerQuerySpec_from_client(
				json.dumps({"document_scope": {"company": company_without_fy}})
			)

	def test_builds_spec_with_dates(self):
		spec = AccountExplorerQuerySpec_from_client(
			json.dumps(
				{
					"document_scope": {
						"company": self.company,
						"from_date": "2020-01-01",
						"to_date": "2020-12-31",
					},
					"analysis_context": {"view_axis": "account_level"},
				}
			)
		)
		self.assertEqual(spec.company, self.company)
		self.assertEqual(getdate(spec.from_date), getdate("2020-01-01"))
		self.assertIsInstance(spec.included_account_names, list)


class TestAccountNumberNormalization(unittest.TestCase):
	def test_persian_digits(self):
		self.assertEqual(normalize_account_number("\u06f1\u06f1"), "11")

	def test_preserves_leading_zeros(self):
		self.assertEqual(normalize_account_number(" 0011 "), "0011")

	def test_alphanumeric_not_treated_as_numeric(self):
		from erpnext_extensions.iran_accounting.account_explorer.account_hierarchy import (
			is_pure_numeric_code,
		)

		normalized = normalize_account_number("11-A")
		self.assertFalse(is_pure_numeric_code(normalized))
