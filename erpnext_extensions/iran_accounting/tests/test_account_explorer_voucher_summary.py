# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

import unittest

import frappe

from erpnext_extensions.iran_accounting.account_explorer import api
from erpnext_extensions.iran_accounting.tests.test_account_explorer_fixtures import (
	build_payload,
	current_fiscal_year,
	enable_wave2b_voucher,
	require_site,
)


class TestAccountExplorerVoucherSummary(unittest.TestCase):
	def setUp(self):
		self.company = require_site(self)
		enable_wave2b_voucher()
		frappe.set_user("Administrator")
		fy = current_fiscal_year(self.company)
		if not fy:
			self.skipTest("No fiscal year")
		self.fiscal_year, self.from_date, self.to_date = fy

	def test_voucher_summary_structure(self):
		payload = build_payload(
			self.company,
			self.fiscal_year,
			self.from_date,
			self.to_date,
			analysis={"view_axis": "voucher", "detail_mode": "summary", "sort_field": "posting_date"},
		)
		result = api.get_voucher_summary(payload)
		self.assertIn("rows", result)
		self.assertIn("totals", result)
		self.assertIn("pagination", result)
		self.assertIn("scoped_debit", result["totals"])
		for row in result["rows"]:
			self.assertIn("scoped_debit", row)
			self.assertIn("scoped_credit", row)
			self.assertIn("scoped_net", row)

	def test_voucher_grouping_single_key(self):
		payload = build_payload(
			self.company,
			self.fiscal_year,
			self.from_date,
			self.to_date,
			analysis={"view_axis": "voucher", "page_size": 200},
		)
		result = api.get_voucher_summary(payload)
		keys = set()
		for row in result["rows"]:
			key = (row["voucher_type"], row["voucher_no"])
			self.assertNotIn(key, keys)
			keys.add(key)

	def test_opening_entries_warning_present(self):
		payload = build_payload(
			self.company,
			self.fiscal_year,
			self.from_date,
			self.to_date,
			analysis={"view_axis": "voucher"},
			document={"include_opening_entries": 0},
		)
		result = api.get_voucher_summary(payload)
		self.assertTrue(any("Opening entries" in warning for warning in result.get("warnings", [])))

	def test_voucher_axis_blocked_when_disabled(self):
		settings = frappe.get_single("Iran Accounting Settings")
		settings.voucher_analysis_enabled = 0
		settings.flags.ignore_permissions = True
		settings.save()
		frappe.db.commit()

		payload = build_payload(
			self.company,
			self.fiscal_year,
			self.from_date,
			self.to_date,
			analysis={"view_axis": "voucher"},
		)
		with self.assertRaises(frappe.ValidationError):
			api.get_voucher_summary(payload)
