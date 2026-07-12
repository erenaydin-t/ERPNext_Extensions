# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

import unittest

import frappe

from erpnext_extensions.iran_accounting.account_explorer.gle_filters import normalize_filter_values
from erpnext_extensions.iran_accounting.account_explorer.query_spec import AccountExplorerQuerySpec_from_client
from erpnext_extensions.iran_accounting.tests.test_account_explorer_fixtures import (
	build_payload,
	current_fiscal_year,
	enable_wave2a_analysis,
	require_site,
)


class TestAccountExplorerMultiselectFilters(unittest.TestCase):
	def setUp(self):
		self.company = require_site(self)
		enable_wave2a_analysis()
		frappe.set_user("Administrator")
		fy = current_fiscal_year(self.company)
		if not fy:
			self.skipTest("No fiscal year")
		self.fiscal_year, self.from_date, self.to_date = fy

	def test_single_string_account_filter(self):
		spec = AccountExplorerQuerySpec_from_client(
			build_payload(
				self.company,
				self.fiscal_year,
				self.from_date,
				self.to_date,
				document={"accounting": {"account": "Cash - _TC"}},
			)
		)
		self.assertEqual(spec.document_scope.accounting.account, "Cash - _TC")
		self.assertEqual(normalize_filter_values(spec.document_scope.accounting.account), ["Cash - _TC"])

	def test_list_account_filter(self):
		accounts = ["Cash - _TC", "Bank - _TC"]
		spec = AccountExplorerQuerySpec_from_client(
			build_payload(
				self.company,
				self.fiscal_year,
				self.from_date,
				self.to_date,
				document={"accounting": {"account": accounts}},
			)
		)
		self.assertEqual(spec.document_scope.accounting.account, accounts)
		self.assertEqual(normalize_filter_values(spec.document_scope.accounting.account), accounts)

	def test_list_party_filter(self):
		parties = ["Customer A", "Customer B"]
		spec = AccountExplorerQuerySpec_from_client(
			build_payload(
				self.company,
				self.fiscal_year,
				self.from_date,
				self.to_date,
				document={"accounting": {"party_type": "Customer", "party": parties}},
			)
		)
		self.assertEqual(spec.document_scope.accounting.party, parties)

	def test_list_dimension_filter(self):
		if not frappe.get_meta("GL Entry").has_field("cost_center"):
			self.skipTest("No cost_center on GL Entry")
		values = ["Main - _TC", "Secondary - _TC"]
		spec = AccountExplorerQuerySpec_from_client(
			build_payload(
				self.company,
				self.fiscal_year,
				self.from_date,
				self.to_date,
				document={"accounting_dimensions": {"cost_center": values}},
			)
		)
		self.assertEqual(spec.document_scope.accounting_dimensions["cost_center"], values)
		self.assertEqual(normalize_filter_values(spec.document_scope.accounting_dimensions["cost_center"]), values)

	def test_mixed_string_and_list_round_trip_payload(self):
		payload = build_payload(
			self.company,
			self.fiscal_year,
			self.from_date,
			self.to_date,
			document={
				"accounting": {"account": "Cash - _TC", "party": ["Customer A", "Customer B"]},
				"accounting_dimensions": {"project": "PROJ-001"},
			},
		)
		spec = AccountExplorerQuerySpec_from_client(payload)
		self.assertEqual(spec.document_scope.accounting.account, "Cash - _TC")
		self.assertEqual(len(spec.document_scope.accounting.party), 2)
		self.assertEqual(spec.document_scope.accounting_dimensions["project"], "PROJ-001")
