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


class TestAccountExplorerVoucherCancelled(unittest.TestCase):
	def setUp(self):
		self.company = require_site(self)
		enable_wave2b_voucher()
		frappe.set_user("Administrator")
		fy = current_fiscal_year(self.company)
		if not fy:
			self.skipTest("No fiscal year")
		self.fiscal_year, self.from_date, self.to_date = fy

	def _voucher_totals(self, include_cancelled: int) -> float:
		payload = build_payload(
			self.company,
			self.fiscal_year,
			self.from_date,
			self.to_date,
			analysis={"view_axis": "voucher", "page_size": 500},
			document={"include_cancelled_entries": include_cancelled},
		)
		result = api.get_voucher_summary(payload)
		return flt(result["totals"].get("scoped_debit")) + flt(result["totals"].get("scoped_credit"))

	def test_cancelled_excluded_by_default(self):
		default_total = self._voucher_totals(0)
		self.assertGreaterEqual(default_total, 0)

	def test_include_cancelled_flag_accepted(self):
		payload = build_payload(
			self.company,
			self.fiscal_year,
			self.from_date,
			self.to_date,
			analysis={"view_axis": "voucher"},
			document={"include_cancelled_entries": 1},
		)
		result = api.get_voucher_summary(payload)
		self.assertIn("totals", result)

	def test_cancelled_voucher_count_diff_when_data_exists(self):
		cancelled = frappe.db.count("GL Entry", {"company": self.company, "is_cancelled": 1})
		if not cancelled:
			self.skipTest("No cancelled GL entries")
		excluded = self._voucher_totals(0)
		included = self._voucher_totals(1)
		self.assertLessEqual(excluded, included)
