# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

import unittest

import frappe

from erpnext_extensions.iran_accounting.account_explorer import api
from erpnext_extensions.iran_accounting.account_explorer.currency_opening import (
	get_currency_opening_balances,
	get_currency_period_balances,
)
from erpnext_extensions.iran_accounting.account_explorer.query_spec import AccountExplorerQuerySpec_from_client
from erpnext_extensions.iran_accounting.tests.test_account_explorer_fixtures import (
	build_payload,
	current_fiscal_year,
	enable_wave2c_unified_party,
	require_site,
)


class TestAccountExplorerCurrencySummary(unittest.TestCase):
	def setUp(self):
		self.company = require_site(self)
		enable_wave2c_unified_party()
		frappe.set_user("Administrator")
		fy = current_fiscal_year(self.company)
		if not fy:
			self.skipTest("No fiscal year")
		self.fiscal_year, self.from_date, self.to_date = fy

	def test_currency_axis_summary_structure(self):
		payload = build_payload(
			self.company,
			self.fiscal_year,
			self.from_date,
			self.to_date,
			analysis={"view_axis": "currency", "sort_field": "currency"},
		)
		result = api.get_currency_summary(payload)
		self.assertIn("rows", result)
		self.assertIn("totals", result)

	def test_currency_axis_blocked_when_disabled(self):
		settings = frappe.get_single("Iran Accounting Settings")
		settings.currency_analysis_enabled = 0
		settings.flags.ignore_permissions = True
		settings.save()
		frappe.db.commit()
		payload = build_payload(
			self.company,
			self.fiscal_year,
			self.from_date,
			self.to_date,
			analysis={"view_axis": "currency"},
		)
		with self.assertRaises(frappe.ValidationError):
			api.get_currency_summary(payload)

	def test_currency_parity_against_gl(self):
		currency_row = frappe.db.sql(
			"""
			select distinct account_currency from `tabGL Entry`
			where company=%s and ifnull(account_currency,'')!='' and is_cancelled=0 limit 1
			""",
			self.company,
		)
		if not currency_row:
			self.skipTest("No account currency GL data")
		currency = currency_row[0][0]

		payload = build_payload(
			self.company,
			self.fiscal_year,
			self.from_date,
			self.to_date,
			analysis={"view_axis": "currency"},
			document={"currency": {"currency_type": "account_currency", "currency": currency}},
		)
		spec = AccountExplorerQuerySpec_from_client(payload, require_dates=True)
		opening = get_currency_opening_balances(spec).get(currency, (0, 0))
		period = get_currency_period_balances(spec).get(currency, (0, 0))
		result = api.get_currency_summary(payload)
		row = next((item for item in result.get("rows") or [] if item.get("currency") == currency), None)
		if not row:
			self.skipTest("Currency row not returned")
		self.assertAlmostEqual(row["period_debit"], period[0], places=2)
		self.assertAlmostEqual(row["period_credit"], period[1], places=2)
		self.assertAlmostEqual(row["opening_debit"], opening[0], places=2)
		self.assertAlmostEqual(row["opening_credit"], opening[1], places=2)
