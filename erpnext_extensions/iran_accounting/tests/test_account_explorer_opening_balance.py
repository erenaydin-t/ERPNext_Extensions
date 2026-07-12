# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

import json
import unittest

import frappe
from erpnext.accounts.report.trial_balance.trial_balance import execute as trial_balance_execute
from frappe.utils import flt

from erpnext_extensions.iran_accounting.account_explorer import api
from erpnext_extensions.iran_accounting.account_explorer.opening_balance import get_account_wise_measures
from erpnext_extensions.iran_accounting.account_explorer.query_spec import (
	AccountExplorerQuerySpec_from_client,
)
from erpnext_extensions.iran_accounting.tests.test_account_explorer_fixtures import (
	current_fiscal_year,
	enable_account_explorer,
	require_site,
)


class TestAccountExplorerOpeningBalance(unittest.TestCase):
	def setUp(self):
		self.company = require_site(self)
		enable_account_explorer()
		frappe.set_user("Administrator")
		fy = current_fiscal_year(self.company)
		if not fy:
			self.skipTest("No fiscal year for test company")
		self.fiscal_year, self.from_date, self.to_date = fy

	def test_parity_with_trial_balance_for_sample_account(self):
		payload = json.dumps(
			{
				"document_scope": {
					"company": self.company,
					"fiscal_year": self.fiscal_year,
					"from_date": self.from_date,
					"to_date": self.to_date,
				}
			}
		)
		spec = AccountExplorerQuerySpec_from_client(payload)
		account = frappe.db.get_value(
			"Account",
			{"company": self.company, "is_group": 0},
			"name",
			order_by="lft",
		)
		if not account:
			self.skipTest("No ledger account in test company")

		explorer = get_account_wise_measures(spec, [account])[account]
		tb_filters = frappe._dict(
			company=self.company,
			fiscal_year=self.fiscal_year,
			from_date=self.from_date,
			to_date=self.to_date,
			show_zero_values=1,
		)
		_columns, data = trial_balance_execute(tb_filters)
		tb_row = next((row for row in data if row.get("account") == account), None)
		self.assertIsNotNone(tb_row)
		self.assertEqual(flt(explorer["period_debit"]), flt(tb_row.get("debit")))
		self.assertEqual(flt(explorer["period_credit"]), flt(tb_row.get("credit")))
		self.assertEqual(flt(explorer["opening_debit"]), flt(tb_row.get("opening_debit")))
		self.assertEqual(flt(explorer["opening_credit"]), flt(tb_row.get("opening_credit")))
		self.assertEqual(flt(explorer["closing_debit"]), flt(tb_row.get("closing_debit")))
		self.assertEqual(flt(explorer["closing_credit"]), flt(tb_row.get("closing_credit")))

	def test_summary_api_returns_global_totals(self):
		payload = json.dumps(
			{
				"document_scope": {
					"company": self.company,
					"fiscal_year": self.fiscal_year,
					"from_date": self.from_date,
					"to_date": self.to_date,
					"hide_zero_rows": 0,
				},
				"analysis_context": {"page_size": 5, "page": 1},
			}
		)
		result = api.get_account_summary(payload)
		self.assertIn("totals", result)
		self.assertIn("pagination", result)
		self.assertIn("total_rows", result["pagination"])
		self.assertIn("has_next", result["pagination"])
