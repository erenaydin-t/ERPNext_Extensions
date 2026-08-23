# Copyright (c) 2026, Farbod Siyahpoosh and contributors
"""Real PCV + ACB integration for GF-13 … GF-17."""

from __future__ import annotations

import json
import unittest

import frappe
from frappe.utils import flt

from erpnext_extensions.iran_accounting.account_explorer import api
from erpnext_extensions.iran_accounting.account_explorer.measures import finalize_measures
from erpnext_extensions.iran_accounting.account_explorer.opening_balance import get_account_wise_measures
from erpnext_extensions.iran_accounting.account_explorer.opening_entry_policy import (
	AccountAxisEngine,
	select_account_axis_engine,
)
from erpnext_extensions.iran_accounting.account_explorer.query_spec import (
	AccountExplorerQuerySpec_from_client,
)
from erpnext_extensions.iran_accounting.tests.opening_policy_direct_gl import (
	direct_gl_policy_measures,
)
from erpnext_extensions.iran_accounting.tests.opening_policy_golden_fixtures import (
	FROM_DATE,
	TO_DATE,
)
from erpnext_extensions.iran_accounting.tests.opening_policy_pcv_acb_fixtures import (
	cleanup_pcv_acb,
	ensure_pcv_acb_context,
)
from erpnext_extensions.iran_accounting.tests.test_account_explorer_fixtures import (
	enable_account_explorer,
	require_site,
)


class TestOpeningPolicyPcvAcbIntegration(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.company = require_site(cls)
		if not cls.company:
			raise unittest.SkipTest("No test company")
		enable_account_explorer()
		frappe.set_user("Administrator")
		cls.ctx = ensure_pcv_acb_context(cls.company)

	@classmethod
	def tearDownClass(cls):
		cleanup_pcv_acb(cls.company)

	def _spec(self, *, include_opening_entries: bool, account: str | None = None):
		document = {
			"company": self.company,
			"fiscal_year": "2026",
			"from_date": str(FROM_DATE),
			"to_date": str(TO_DATE),
			"hide_zero_rows": 0,
			"status": {
				"include_opening_entries": 1 if include_opening_entries else 0,
				"include_cancelled_entries": 0,
				"include_period_closing_vouchers": 0,
				"include_default_finance_book_entries": 1,
			},
		}
		if account:
			document["accounting"] = {"account": account}
		payload = json.dumps(
			{
				"document_scope": document,
				"analysis_context": {"view_axis": "account_level", "page_size": 50, "page": 1},
			}
		)
		return AccountExplorerQuerySpec_from_client(payload, require_dates=True)

	def _account_measures(self, *, include_opening_entries: bool, filtered: bool = False) -> dict:
		spec = self._spec(
			include_opening_entries=include_opening_entries,
			account=self.ctx["target_account"] if filtered else None,
		)
		rows = get_account_wise_measures(spec, [self.ctx["target_account"]])
		return finalize_measures(rows[self.ctx["target_account"]])

	def _direct(self, *, include_opening_entries: bool, filtered: bool = False) -> dict:
		return direct_gl_policy_measures(
			self.company,
			str(FROM_DATE),
			str(TO_DATE),
			include_opening_entries=include_opening_entries,
			account=self.ctx["target_account"] if filtered else None,
		)

	def test_gf13_off_e3_fallback_real_acb(self):
		spec_unfiltered = self._spec(include_opening_entries=False)
		engine = select_account_axis_engine(spec_unfiltered)
		self.assertEqual(engine, AccountAxisEngine.E3_SCOPED_GL)
		self.assertTrue(self.ctx["acb_opening_baked"])

		measures = self._account_measures(include_opening_entries=False, filtered=True)
		direct = self._direct(include_opening_entries=False, filtered=True)
		for key in ("opening_debit", "opening_credit", "period_debit", "period_credit", "net_balance"):
			self.assertEqual(flt(measures[key]), flt(direct[key]), key)

		# Normal pre-PCV 800 retained; opening-flagged 200 excluded under OFF
		self.assertEqual(flt(measures["opening_debit"]), 800.0)
		opening_flagged = frappe.db.sql(
			"""
			select coalesce(sum(debit-credit),0)
			from `tabGL Entry`
			where company=%s and account=%s and is_opening='Yes' and posting_date <= %s and is_cancelled=0
			""",
			(self.company, self.ctx["target_account"], self.ctx["pcv_end"]),
		)[0][0]
		self.assertEqual(flt(opening_flagged), 200.0)

	def test_gf14_on_historical_opening_once_in_opening(self):
		spec_unfiltered = self._spec(include_opening_entries=True)
		engine = select_account_axis_engine(spec_unfiltered)
		self.assertIn(
			engine,
			(AccountAxisEngine.E1_TB_DELTA, AccountAxisEngine.E2_TB_GAP_SUPPLEMENT),
		)
		measures = self._account_measures(include_opening_entries=True, filtered=True)
		direct = self._direct(include_opening_entries=True, filtered=True)
		for key in ("opening_debit", "opening_credit", "period_debit", "period_credit", "net_balance"):
			self.assertEqual(flt(measures[key]), flt(direct[key]), key)
		# 800 normal + 200 historical opening + 150 gap opening (all pre-period under ON)
		self.assertEqual(flt(measures["opening_debit"]), 1150.0)
		self.assertEqual(flt(measures["period_debit"]), 350.0)  # gap 150 + in-period opening 300 + normal 50

	def test_gf15_gap_opening_off_on(self):
		off = self._account_measures(include_opening_entries=False, filtered=True)
		on = self._account_measures(include_opening_entries=True, filtered=True)
		self.assertEqual(flt(off["opening_debit"]), 800.0)
		self.assertEqual(flt(on["opening_debit"]), 1150.0)  # 800 + 200 + 150 pre-period opening

	def test_gf16_in_period_opening_off_on(self):
		off = self._account_measures(include_opening_entries=False, filtered=True)
		on = self._account_measures(include_opening_entries=True, filtered=True)
		self.assertEqual(flt(off["period_debit"]), 50.0)
		self.assertEqual(flt(on["period_debit"]), 350.0)

	def test_gf17_off_normal_retained_opening_flagged_removed(self):
		measures = self._account_measures(include_opening_entries=False, filtered=True)
		self.assertEqual(flt(measures["opening_debit"]), 800.0)
		self.assertEqual(flt(measures["period_debit"]), 50.0)

	def test_gf17_on_normal_plus_opening_once(self):
		measures = self._account_measures(include_opening_entries=True, filtered=True)
		self.assertEqual(flt(measures["opening_debit"]), 1150.0)
		self.assertEqual(flt(measures["period_debit"]), 350.0)

	def test_api_account_summary_matches_direct_gl_off(self):
		payload = json.dumps(
			{
				"document_scope": {
					"company": self.company,
					"fiscal_year": "2026",
					"from_date": str(FROM_DATE),
					"to_date": str(TO_DATE),
					"hide_zero_rows": 0,
					"accounting": {"account": self.ctx["target_account"]},
					"status": {"include_opening_entries": 0},
				},
				"analysis_context": {"view_axis": "account_level", "page_size": 50, "page": 1},
			}
		)
		result = api.get_account_summary(payload)
		direct = self._direct(include_opening_entries=False, filtered=True)
		totals = finalize_measures(result["totals"])
		for key in ("opening_debit", "period_debit", "net_balance"):
			self.assertEqual(flt(totals[key]), flt(direct[key]), key)
