# Copyright (c) 2026, Farbod Siyahpoosh and contributors
"""Production-builder integration for OpeningEntryPolicy GF-01 … GF-17."""

from __future__ import annotations

import json
import unittest

import frappe
from frappe.utils import flt

from erpnext_extensions.iran_accounting.account_explorer import api
from erpnext_extensions.iran_accounting.account_explorer.measures import finalize_measures
from erpnext_extensions.iran_accounting.account_explorer.opening_balance import get_account_wise_measures
from erpnext_extensions.iran_accounting.account_explorer.opening_entry_policy import (
	assert_closing_invariant,
	assert_off_zero_opening_flagged,
	assert_on_partition,
)
from erpnext_extensions.iran_accounting.account_explorer.party_opening import get_unspecified_party_measures
from erpnext_extensions.iran_accounting.account_explorer.query_spec import (
	AccountExplorerQuerySpec_from_client,
)
from erpnext_extensions.iran_accounting.tests.opening_policy_golden_fixtures import (
	ALL_GOLDEN_FIXTURES,
	GOLDEN_FIXTURES_BY_ID,
)
from erpnext_extensions.iran_accounting.tests.opening_policy_production_fixtures import (
	cleanup_gf_production,
	ensure_gf_production_context,
)
from erpnext_extensions.iran_accounting.tests.test_account_explorer_fixtures import (
	current_fiscal_year,
	enable_wave2b_voucher,
	require_site,
)

MEASURE_KEYS = ("opening_debit", "opening_credit", "period_debit", "period_credit")


def _spec_payload(
	company: str,
	fiscal_year: str,
	ctx: dict,
	*,
	include_opening_entries: bool,
	document_overrides: dict | None = None,
) -> str:
	document = {
		"company": company,
		"fiscal_year": fiscal_year,
		"from_date": ctx["from_date"],
		"to_date": ctx["to_date"],
		"hide_zero_rows": 0,
		"accounting": {"account": ctx["target_account"]},
		"status": {
			"include_opening_entries": 1 if include_opening_entries else 0,
			"include_cancelled_entries": 0,
			"include_period_closing_vouchers": 0,
			"include_default_finance_book_entries": 1,
		},
	}
	if document_overrides:
		for key, value in document_overrides.items():
			if isinstance(value, dict) and isinstance(document.get(key), dict):
				document[key] = {**document[key], **value}
			else:
				document[key] = value
	return json.dumps(
		{
			"document_scope": document,
			"analysis_context": {"view_axis": "account_level", "page_size": 50, "page": 1},
		}
	)


class TestOpeningPolicyProductionIntegration(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.company = require_site(cls)
		if not cls.company:
			raise unittest.SkipTest("No test company")
		enable_wave2b_voucher()
		frappe.set_user("Administrator")
		fy = current_fiscal_year(cls.company)
		if not fy:
			raise unittest.SkipTest("No fiscal year")
		cls.fiscal_year, cls.fy_from, cls.fy_to = fy

	def tearDown(self):
		cleanup_gf_production(self.company)

	def _assert_measures(self, actual: dict, expected: dict, label: str):
		for key in MEASURE_KEYS:
			self.assertEqual(flt(actual.get(key)), flt(expected.get(key)), f"{label}/{key}")

	def _account_measures(
		self,
		ctx: dict,
		*,
		include_opening_entries: bool,
		document_overrides: dict | None = None,
	) -> dict:
		payload = _spec_payload(
			self.company,
			self.fiscal_year,
			ctx,
			include_opening_entries=include_opening_entries,
			document_overrides=document_overrides,
		)
		spec = AccountExplorerQuerySpec_from_client(payload, require_dates=True)
		rows = get_account_wise_measures(spec, [ctx["target_account"]])
		return finalize_measures(rows[ctx["target_account"]])

	def _document_overrides_for_fixture(self, fixture_id: str) -> dict | None:
		fixture = GOLDEN_FIXTURES_BY_ID[fixture_id]
		finance_books = {
			str(row.get("finance_book"))
			for row in fixture.rows
			if row.get("finance_book") not in (None, "")
		}
		if not finance_books:
			return None
		return {
			"finance_book": next(iter(finance_books)),
			"status": {"include_default_finance_book_entries": 0},
		}

	def test_gf_production_matrix_account_axis(self):
		for fixture in ALL_GOLDEN_FIXTURES:
			with self.subTest(fixture_id=fixture.fixture_id):
				ctx = ensure_gf_production_context(self.company, fixture.fixture_id)
				doc_overrides = self._document_overrides_for_fixture(fixture.fixture_id)
				off = self._account_measures(
					ctx, include_opening_entries=False, document_overrides=doc_overrides
				)
				on = self._account_measures(
					ctx, include_opening_entries=True, document_overrides=doc_overrides
				)
				self._assert_measures(off, fixture.expected_off, f"{fixture.fixture_id}/OFF")
				self._assert_measures(on, fixture.expected_on, f"{fixture.fixture_id}/ON")
				assert_closing_invariant(off)
				assert_closing_invariant(on)

	def test_gf12_no_double_count_production(self):
		ctx = ensure_gf_production_context(self.company, "GF-12")
		on = self._account_measures(ctx, include_opening_entries=True)
		fixture = GOLDEN_FIXTURES_BY_ID["GF-12"]
		self._assert_measures(on, fixture.expected_on, "GF-12/ON")
		payload = _spec_payload(self.company, self.fiscal_year, ctx, include_opening_entries=True)
		spec = AccountExplorerQuerySpec_from_client(payload, require_dates=True)
		# Production rows on target account only; invariants on fixture row semantics
		assert_on_partition(fixture.rows, on, fixture.window)

	def test_gf09_unassigned_party_production(self):
		ctx = ensure_gf_production_context(self.company, "GF-09")
		payload = json.dumps(
			{
				"document_scope": {
					"company": self.company,
					"fiscal_year": self.fiscal_year,
					"from_date": ctx["from_date"],
					"to_date": ctx["to_date"],
					"hide_zero_rows": 0,
					"accounting": {"account": ctx["target_account"]},
					"status": {"include_opening_entries": 0, "include_cancelled_entries": 0},
				},
				"analysis_context": {"view_axis": "party", "page_size": 50, "page": 1},
			}
		)
		spec = AccountExplorerQuerySpec_from_client(payload, require_dates=True)
		unspecified = finalize_measures(get_unspecified_party_measures(spec, []))
		fixture = GOLDEN_FIXTURES_BY_ID["GF-09"]
		self._assert_measures(unspecified, fixture.expected_off, "GF-09/party-OFF")

	def test_account_summary_api_off_on(self):
		ctx = ensure_gf_production_context(self.company, "GF-10")
		for include in (False, True):
			payload = _spec_payload(
				self.company, self.fiscal_year, ctx, include_opening_entries=include
			)
			result = api.get_account_summary(payload)
			totals = finalize_measures(result["totals"])
			expected = GOLDEN_FIXTURES_BY_ID["GF-10"].expected_off
			if include:
				expected = GOLDEN_FIXTURES_BY_ID["GF-10"].expected_on
			self._assert_measures(totals, expected, f"GF-10/api/{include}")

	def test_axis_matrix_account_filtered_off_on(self):
		"""Axis | OFF Filtered | ON Filtered for account axis via scoped GL."""
		ctx = ensure_gf_production_context(self.company, "GF-02")
		for include in (False, True):
			payload = _spec_payload(
				self.company, self.fiscal_year, ctx, include_opening_entries=include
			)
			spec = AccountExplorerQuerySpec_from_client(payload, require_dates=True)
			measures = finalize_measures(
				get_account_wise_measures(spec, [ctx["target_account"]])[ctx["target_account"]]
			)
			fixture = GOLDEN_FIXTURES_BY_ID["GF-02"]
			expected = fixture.expected_off if not include else fixture.expected_on
			self._assert_measures(measures, expected, f"matrix/{include}")

	def test_off_tb_parity_normal_gl_intentional_on_deviation_documented(self):
		"""OFF unfiltered E1 remains aligned with ERPNext TB for normal GL (GF-01)."""
		from erpnext.accounts.report.trial_balance.trial_balance import execute as tb_execute

		ctx = ensure_gf_production_context(self.company, "GF-01")
		payload = json.dumps(
			{
				"document_scope": {
					"company": self.company,
					"fiscal_year": self.fiscal_year,
					"from_date": ctx["from_date"],
					"to_date": ctx["to_date"],
					"hide_zero_rows": 0,
					"status": {"include_opening_entries": 0},
				}
			}
		)
		spec = AccountExplorerQuerySpec_from_client(payload, require_dates=True)
		explorer = get_account_wise_measures(spec, [ctx["target_account"]])[ctx["target_account"]]
		_columns, data = tb_execute(
			frappe._dict(
				company=self.company,
				fiscal_year=self.fiscal_year,
				from_date=ctx["from_date"],
				to_date=ctx["to_date"],
				show_zero_values=1,
			)
		)
		tb_row = next((row for row in data if row.get("account") == ctx["target_account"]), None)
		self.assertIsNotNone(tb_row)
		self.assertEqual(flt(explorer["opening_debit"]), flt(tb_row.get("opening_debit")))

	def test_on_in_period_opening_in_turnover_not_erpnext_tb_parity(self):
		"""ON intentionally includes in-period is_opening rows in turnover (GF-05)."""
		ctx = ensure_gf_production_context(self.company, "GF-05")
		on = self._account_measures(ctx, include_opening_entries=True)
		self._assert_measures(on, GOLDEN_FIXTURES_BY_ID["GF-05"].expected_on, "GF-05/ON")
		self.assertEqual(flt(on["period_debit"]), 300.0)
		self.assertEqual(flt(on["opening_debit"]), 0.0)
