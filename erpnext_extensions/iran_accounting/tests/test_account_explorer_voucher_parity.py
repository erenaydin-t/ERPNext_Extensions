# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

import unittest

import frappe
from frappe.utils import flt

from erpnext_extensions.iran_accounting.account_explorer import api
from erpnext_extensions.iran_accounting.tests.test_account_explorer_fixtures import (
	build_payload,
	current_fiscal_year,
	enable_wave2b_voucher,
	require_site,
)


class TestAccountExplorerVoucherParity(unittest.TestCase):
	def setUp(self):
		self.company = require_site(self)
		enable_wave2b_voucher()
		frappe.set_user("Administrator")
		fy = current_fiscal_year(self.company)
		if not fy:
			self.skipTest("No fiscal year")
		self.fiscal_year, self.from_date, self.to_date = fy

	def test_voucher_scoped_totals_match_gl_lines(self):
		account = frappe.db.get_value(
			"GL Entry",
			{"company": self.company, "is_cancelled": 0},
			"account",
		)
		if not account:
			self.skipTest("No GL account data")

		gl_total = frappe.db.sql(
			"""
			select coalesce(sum(debit), 0) + coalesce(sum(credit), 0) as total
			from `tabGL Entry`
			where company = %s
			  and is_cancelled = 0
			  and is_opening = 'No'
			  and posting_date between %s and %s
			  and account = %s
			""",
			(self.company, self.from_date, self.to_date, account),
		)[0][0]

		payload = build_payload(
			self.company,
			self.fiscal_year,
			self.from_date,
			self.to_date,
			analysis={
				"view_axis": "voucher",
				"account_scope": {"mode": "account", "selected_account": account},
			},
		)
		result = api.get_voucher_summary(payload)
		explorer_total = flt(result["totals"].get("scoped_debit")) + flt(result["totals"].get("scoped_credit"))
		self.assertAlmostEqual(explorer_total, flt(gl_total), places=2)
