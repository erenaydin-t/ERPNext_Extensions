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


class TestAccountExplorerVoucherGl(unittest.TestCase):
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

	def test_grouped_gl_structure(self):
		payload = build_payload(
			self.company,
			self.fiscal_year,
			self.from_date,
			self.to_date,
			analysis={
				"view_axis": "voucher",
				"detail_mode": "grouped_gl",
				"voucher_scope": {
					"voucher_type": self.sample.voucher_type,
					"voucher_no": self.sample.voucher_no,
				},
			},
		)
		result = api.get_grouped_gl_entries(payload)
		self.assertIn("rows", result)
		self.assertIn("voucher_header", result)
		self.assertIn("debit", result["totals"])
		for row in result["rows"]:
			self.assertIn("account", row)
			self.assertIn("debit", row)
			self.assertIn("credit", row)

	def test_grouped_gl_groups_by_account(self):
		payload = build_payload(
			self.company,
			self.fiscal_year,
			self.from_date,
			self.to_date,
			analysis={
				"view_axis": "voucher",
				"detail_mode": "grouped_gl",
				"voucher_scope": {
					"voucher_type": self.sample.voucher_type,
					"voucher_no": self.sample.voucher_no,
				},
			},
		)
		result = api.get_grouped_gl_entries(payload)
		accounts = [row["account"] for row in result["rows"]]
		self.assertEqual(len(accounts), len(set(accounts)))
