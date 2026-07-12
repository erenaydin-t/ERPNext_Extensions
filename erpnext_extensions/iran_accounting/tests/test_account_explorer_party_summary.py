# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

import unittest

import frappe

from erpnext_extensions.iran_accounting.account_explorer import api
from erpnext_extensions.iran_accounting.account_explorer.constants import VIRTUAL_PARTY_UNSPECIFIED_KEY
from erpnext_extensions.iran_accounting.tests.test_account_explorer_fixtures import (
	build_payload,
	current_fiscal_year,
	enable_wave2a_analysis,
	require_site,
)


class TestAccountExplorerPartySummary(unittest.TestCase):
	def setUp(self):
		self.company = require_site(self)
		enable_wave2a_analysis()
		frappe.set_user("Administrator")
		fy = current_fiscal_year(self.company)
		if not fy:
			self.skipTest("No fiscal year")
		self.fiscal_year, self.from_date, self.to_date = fy

	def test_party_summary_structure(self):
		payload = build_payload(
			self.company,
			self.fiscal_year,
			self.from_date,
			self.to_date,
			analysis={"view_axis": "party", "sort_field": "party_type"},
		)
		result = api.get_party_summary(payload)
		self.assertIn("rows", result)
		self.assertIn("totals", result)
		self.assertIn("pagination", result)
		for row in result["rows"]:
			if row.get("row_key") != VIRTUAL_PARTY_UNSPECIFIED_KEY:
				self.assertIn("party_type", row)
				self.assertIn("party", row)

	def test_party_pagination(self):
		payload = build_payload(
			self.company,
			self.fiscal_year,
			self.from_date,
			self.to_date,
			analysis={"view_axis": "party", "page_size": 1, "page": 1},
		)
		page1 = api.get_party_summary(payload)
		self.assertLessEqual(len(page1["rows"]), 1)

	def test_party_selected_party_filter(self):
		customer = frappe.db.get_value("Customer", {}, "name")
		if not customer:
			self.skipTest("No customer")
		payload = build_payload(
			self.company,
			self.fiscal_year,
			self.from_date,
			self.to_date,
			analysis={
				"view_axis": "party",
				"party_scope": {"party_type": "Customer", "selected_party": customer},
			},
		)
		result = api.get_party_summary(payload)
		for row in result["rows"]:
			if row.get("party"):
				self.assertEqual(row["party"], customer)

	def test_party_parity_with_trial_balance_for_party(self):
		from erpnext.accounts.report.trial_balance_for_party.trial_balance_for_party import (
			get_balances_within_period,
			get_opening_balances,
			toggle_debit_credit,
		)

		account = frappe.db.get_value("Account", {"company": self.company, "is_group": 0}, "name")
		if not account:
			self.skipTest("No leaf account")
		party_type = "Customer"
		party = frappe.db.sql(
			"""
			select distinct party from `tabGL Entry`
			where company=%s and account=%s and party_type=%s and party!='' and is_cancelled=0
			limit 1
			""",
			(self.company, account, party_type),
		)
		if not party:
			self.skipTest("No customer GL on account")
		party = party[0][0]

		filters = frappe._dict(
			company=self.company,
			from_date=self.from_date,
			to_date=self.to_date,
			party_type=party_type,
		)
		opening = get_opening_balances(filters, [account]).get(party, [0, 0])
		period = get_balances_within_period(filters, [account]).get(party, [0, 0])
		closing_debit, closing_credit = toggle_debit_credit(
			opening[0] + period[0], opening[1] + period[1]
		)

		payload = build_payload(
			self.company,
			self.fiscal_year,
			self.from_date,
			self.to_date,
			analysis={
				"view_axis": "party",
				"party_scope": {"party_type": party_type, "selected_party": party},
				"account_scope": {"mode": "account", "selected_account": account},
			},
			document={"hide_zero_rows": 0},
		)
		result = api.get_party_summary(payload)
		self.assertEqual(len(result["rows"]), 1)
		row = result["rows"][0]
		self.assertAlmostEqual(row["opening_debit"], opening[0], places=2)
		self.assertAlmostEqual(row["opening_credit"], opening[1], places=2)
		self.assertAlmostEqual(row["period_debit"], period[0], places=2)
		self.assertAlmostEqual(row["period_credit"], period[1], places=2)
		self.assertAlmostEqual(row["debit_balance"], closing_debit, places=2)
		self.assertAlmostEqual(row["credit_balance"], closing_credit, places=2)
