# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

import json
import unittest

import frappe

from erpnext_extensions.iran_accounting.account_explorer import api
from erpnext_extensions.iran_accounting.account_explorer.query_spec import AccountExplorerQuerySpec_from_client
from erpnext_extensions.iran_accounting.tests.test_account_explorer_fixtures import (
	build_payload,
	current_fiscal_year,
	default_document_scope,
	enable_wave2c_unified_party,
	require_site,
)


class TestAccountExplorerDocumentScopeUI(unittest.TestCase):
	def setUp(self):
		self.company = require_site(self)
		enable_wave2c_unified_party()
		frappe.set_user("Administrator")
		fy = current_fiscal_year(self.company)
		if not fy:
			self.skipTest("No fiscal year")
		self.fiscal_year, self.from_date, self.to_date = fy

	def test_filter_state_serialization_roundtrip(self):
		document = default_document_scope(self.company, self.fiscal_year, self.from_date, self.to_date)
		document.update(
			{
				"finance_book": "Main Finance Book",
				"voucher": {
					"voucher_type": "Journal Entry",
					"voucher_no": "JV-0001",
					"against_voucher_type": "Sales Invoice",
					"against_voucher_no": "SINV-0001",
					"reference_no": "REF-001",
				},
				"accounting": {
					"account": "Cash - _TC",
					"party_type": "Customer",
					"party": "Customer A",
				},
				"accounting_dimensions": {"cost_center": "Main - _TC"},
				"currency": {"currency_type": "transaction_currency", "currency": "USD"},
				"status": {
					"include_opening_entries": 0,
					"include_cancelled_entries": 1,
					"include_default_finance_book_entries": 0,
					"include_period_closing_vouchers": 1,
				},
			}
		)
		payload = build_payload(
			self.company,
			self.fiscal_year,
			self.from_date,
			self.to_date,
			document=document,
			analysis={"view_axis": "account_level"},
		)
		result = api.validate_document_scope(payload)
		self.assertTrue(result.get("ok"))
		scope = result.get("document_scope") or {}
		self.assertEqual(scope["finance_book"], "Main Finance Book")
		self.assertEqual(scope["voucher"]["voucher_no"], "JV-0001")
		self.assertEqual(scope["accounting"]["party_type"], "Customer")
		self.assertEqual(scope["accounting_dimensions"]["cost_center"], "Main - _TC")
		self.assertEqual(scope["currency"]["currency_type"], "transaction_currency")
		self.assertEqual(scope["currency"]["currency"], "USD")
		self.assertEqual(scope["status"]["include_cancelled_entries"], 1)

	def test_voucher_filters_parse(self):
		spec = AccountExplorerQuerySpec_from_client(
			build_payload(
				self.company,
				self.fiscal_year,
				self.from_date,
				self.to_date,
				document={
					"voucher": {
						"voucher_type": "Payment Entry",
						"voucher_no": "PE-0001",
						"against_voucher_type": "Purchase Invoice",
						"against_voucher_no": "PINV-0001",
						"reference_no": "BILL-001",
					}
				},
			)
		)
		self.assertEqual(spec.document_scope.voucher.voucher_type, "Payment Entry")
		self.assertEqual(spec.document_scope.voucher.reference_no, "BILL-001")

	def test_dimension_filters_parse(self):
		if not frappe.get_meta("GL Entry").has_field("cost_center"):
			self.skipTest("No cost_center on GL Entry")
		spec = AccountExplorerQuerySpec_from_client(
			build_payload(
				self.company,
				self.fiscal_year,
				self.from_date,
				self.to_date,
				document={"accounting_dimensions": {"cost_center": "Main - _TC", "project": "PROJ-001"}},
			)
		)
		self.assertEqual(spec.document_scope.accounting_dimensions.get("cost_center"), "Main - _TC")
		self.assertEqual(spec.document_scope.accounting_dimensions.get("project"), "PROJ-001")

	def test_currency_filters_parse(self):
		spec = AccountExplorerQuerySpec_from_client(
			build_payload(
				self.company,
				self.fiscal_year,
				self.from_date,
				self.to_date,
				document={"currency": {"currency_type": "account_currency", "currency": "IRR"}},
				analysis={"view_axis": "currency"},
			)
		)
		self.assertEqual(spec.document_scope.currency.currency_type, "account_currency")
		self.assertEqual(spec.document_scope.currency.currency, "IRR")

	def test_list_values_supported_for_multi_select_preparation(self):
		spec = AccountExplorerQuerySpec_from_client(
			build_payload(
				self.company,
				self.fiscal_year,
				self.from_date,
				self.to_date,
				document={
					"accounting": {
						"account": ["Cash - _TC", "Bank - _TC"],
						"party": ["Customer A", "Customer B"],
					},
					"accounting_dimensions": {"cost_center": ["Main - _TC", "Secondary - _TC"]},
				},
			)
		)
		self.assertEqual(len(spec.document_scope.accounting.account), 2)
		self.assertEqual(len(spec.document_scope.accounting.party), 2)
		self.assertEqual(len(spec.document_scope.accounting_dimensions["cost_center"]), 2)

	def test_reset_defaults_preserve_document_scope_structure(self):
		document = default_document_scope(self.company, self.fiscal_year, self.from_date, self.to_date)
		required_keys = {
			"company",
			"fiscal_year",
			"from_date",
			"to_date",
			"finance_book",
			"voucher",
			"accounting",
			"accounting_dimensions",
			"currency",
			"status",
		}
		self.assertTrue(required_keys.issubset(document.keys()))
		self.assertIn("currency_type", document["currency"])
		self.assertIn("include_opening_entries", document["status"])

		spec = AccountExplorerQuerySpec_from_client(
			build_payload(self.company, self.fiscal_year, self.from_date, self.to_date)
		)
		self.assertIsNone(spec.document_scope.finance_book)
		self.assertIsNone(spec.document_scope.voucher.voucher_type)
		self.assertIsNone(spec.document_scope.accounting.account)
		self.assertEqual(spec.document_scope.currency.currency_type, "account_currency")

	def test_validate_document_scope_requires_wrapper(self):
		with self.assertRaises(Exception):
			api.validate_document_scope(json.dumps({"analysis_context": {"view_axis": "account_level"}}))

	def test_analysis_context_unchanged_when_applying_filters(self):
		payload = build_payload(
			self.company,
			self.fiscal_year,
			self.from_date,
			self.to_date,
			document={"accounting_dimensions": {"cost_center": "Main - _TC"}},
			analysis={
				"view_axis": "dimension",
				"dimension_scope": {"dimension_type": "cost_center"},
			},
		)
		spec = AccountExplorerQuerySpec_from_client(payload)
		self.assertEqual(spec.view_axis, "dimension")
		self.assertEqual(spec.dimension_scope.dimension_type, "cost_center")
		self.assertEqual(spec.document_scope.accounting_dimensions.get("cost_center"), "Main - _TC")
