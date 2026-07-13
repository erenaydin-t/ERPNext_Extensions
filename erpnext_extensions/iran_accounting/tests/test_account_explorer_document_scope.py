# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

import json
import unittest

import frappe

from erpnext_extensions.iran_accounting.account_explorer import api
from erpnext_extensions.iran_accounting.account_explorer.query_spec import (
	AccountExplorerQuerySpec_from_client,
	AccountExplorerValidationError,
)
from erpnext_extensions.iran_accounting.tests.test_account_explorer_fixtures import (
	build_payload,
	current_fiscal_year,
	default_document_scope,
	enable_wave2c_unified_party,
	require_site,
)


class TestAccountExplorerDocumentScope(unittest.TestCase):
	def setUp(self):
		self.company = require_site(self)
		enable_wave2c_unified_party()
		frappe.set_user("Administrator")
		fy = current_fiscal_year(self.company)
		if not fy:
			self.skipTest("No fiscal year")
		self.fiscal_year, self.from_date, self.to_date = fy

	def test_requires_document_scope_wrapper(self):
		with self.assertRaises(AccountExplorerValidationError):
			AccountExplorerQuerySpec_from_client(
				json.dumps({"analysis_context": {"view_axis": "account_level"}})
			)

	def test_parses_nested_document_scope(self):
		spec = AccountExplorerQuerySpec_from_client(
			build_payload(
				self.company,
				self.fiscal_year,
				self.from_date,
				self.to_date,
				document={
					"accounting_dimensions": {"cost_center": "Main - _TC"},
					"currency": {"currency_type": "account_currency", "currency": "USD"},
				},
			)
		)
		self.assertEqual(spec.document_scope.accounting_dimensions.get("cost_center"), "Main - _TC")
		self.assertEqual(spec.document_scope.currency.currency, "USD")

	def test_all_summary_apis_require_document_scope(self):
		payload = build_payload(
			self.company,
			self.fiscal_year,
			self.from_date,
			self.to_date,
			analysis={"view_axis": "account_level"},
		)
		self.assertIn("rows", api.get_account_summary(payload))

	def test_dimension_filter_applies_on_party_axis(self):
		cc = frappe.db.sql(
			"""
			select distinct cost_center from `tabGL Entry`
			where company=%s and ifnull(cost_center,'')!='' and is_cancelled=0 limit 1
			""",
			self.company,
		)
		if not cc:
			self.skipTest("No cost center GL data")
		payload = build_payload(
			self.company,
			self.fiscal_year,
			self.from_date,
			self.to_date,
			analysis={"view_axis": "party"},
			document={"accounting_dimensions": {"cost_center": cc[0][0]}},
		)
		result = api.get_party_summary(payload)
		self.assertIn("rows", result)

	def test_currency_filter_applies_on_account_axis(self):
		currency = frappe.db.sql(
			"""
			select distinct account_currency from `tabGL Entry`
			where company=%s and ifnull(account_currency,'')!='' and is_cancelled=0 limit 1
			""",
			self.company,
		)
		if not currency:
			self.skipTest("No account currency GL data")
		payload = build_payload(
			self.company,
			self.fiscal_year,
			self.from_date,
			self.to_date,
			document={"currency": {"currency_type": "account_currency", "currency": currency[0][0]}},
		)
		result = api.get_account_summary(payload)
		self.assertIn("rows", result)

	def test_document_and_analysis_filters_intersect(self):
		customer = frappe.db.sql(
			"""
			select distinct party from `tabGL Entry`
			where company=%s and party_type='Customer' and party!='' and is_cancelled=0 limit 1
			""",
			self.company,
		)
		if not customer:
			self.skipTest("No customer GL data")
		payload = build_payload(
			self.company,
			self.fiscal_year,
			self.from_date,
			self.to_date,
			analysis={
				"view_axis": "party",
				"party_scope": {"party_type": "Customer", "selected_party": customer[0][0]},
			},
			document={"accounting": {"party_type": "Customer", "party": customer[0][0]}},
		)
		result = api.get_party_summary(payload)
		for row in result.get("rows") or []:
			if row.get("party"):
				self.assertEqual(row["party"], customer[0][0])
