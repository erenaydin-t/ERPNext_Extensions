# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

import unittest

import frappe

from erpnext_extensions.iran_accounting.account_explorer import api
from erpnext_extensions.iran_accounting.tests.test_account_explorer_fixtures import (
	build_payload,
	create_test_unified_accounting_party,
	current_fiscal_year,
	delete_test_unified_accounting_party,
	enable_wave2c_unified_party,
	require_site,
)


class TestAccountExplorerUnifiedPartySummary(unittest.TestCase):
	def setUp(self):
		self.company = require_site(self)
		enable_wave2c_unified_party()
		frappe.set_user("Administrator")
		fy = current_fiscal_year(self.company)
		if not fy:
			self.skipTest("No fiscal year")
		self.fiscal_year, self.from_date, self.to_date = fy
		self.created_uaps: list[str] = []

	def tearDown(self):
		for name in reversed(self.created_uaps):
			delete_test_unified_accounting_party(name)

	def _customers_with_gl(self, limit: int = 2) -> list[str]:
		rows = frappe.db.sql(
			"""
			select distinct party
			from `tabGL Entry`
			where company=%s and party_type='Customer' and party!='' and is_cancelled=0
			limit %s
			""",
			(self.company, limit),
		)
		return [row[0] for row in rows]

	def test_unified_party_summary_structure(self):
		payload = build_payload(
			self.company,
			self.fiscal_year,
			self.from_date,
			self.to_date,
			analysis={"view_axis": "unified_party", "sort_field": "display_title"},
		)
		result = api.get_unified_party_summary(payload)
		self.assertIn("rows", result)
		self.assertIn("totals", result)
		self.assertIn("pagination", result)

	def test_unified_party_rollup_matches_member_totals(self):
		customers = self._customers_with_gl(2)
		if len(customers) < 1:
			self.skipTest("No customer GL activity")
		uap_name = create_test_unified_accounting_party(
			[("Customer", customer) for customer in customers[: min(2, len(customers))]],
			unified_name="Rollup Test UAP",
		)
		self.created_uaps.append(uap_name)

		summary_payload = build_payload(
			self.company,
			self.fiscal_year,
			self.from_date,
			self.to_date,
			analysis={"view_axis": "unified_party"},
		)
		summary = api.get_unified_party_summary(summary_payload)
		uap_row = next((row for row in summary["rows"] if row.get("unified_party") == uap_name), None)
		if not uap_row:
			self.skipTest("Unified party row not visible in summary")

		breakdown_payload = build_payload(
			self.company,
			self.fiscal_year,
			self.from_date,
			self.to_date,
			analysis={
				"view_axis": "unified_party",
				"unified_party_scope": {"selected_unified_party": uap_name},
			},
		)
		breakdown = api.get_unified_party_member_breakdown(breakdown_payload)
		member_debit = sum(row.get("period_debit") or 0 for row in breakdown["rows"])
		member_credit = sum(row.get("period_credit") or 0 for row in breakdown["rows"])
		self.assertAlmostEqual(uap_row.get("period_debit") or 0, member_debit, places=2)
		self.assertAlmostEqual(uap_row.get("period_credit") or 0, member_credit, places=2)

	def test_voucher_axis_filters_by_selected_unified_party(self):
		customers = self._customers_with_gl(1)
		if not customers:
			self.skipTest("No customer GL activity")
		customer = customers[0]
		uap_name = create_test_unified_accounting_party([("Customer", customer)], unified_name="Voucher Scope UAP")
		self.created_uaps.append(uap_name)

		payload = build_payload(
			self.company,
			self.fiscal_year,
			self.from_date,
			self.to_date,
			analysis={
				"view_axis": "voucher",
				"unified_party_scope": {"selected_unified_party": uap_name},
			},
		)
		result = api.get_voucher_summary(payload)
		for row in result.get("rows") or []:
			if row.get("party_type") == "Customer" and row.get("party"):
				self.assertEqual(row["party"], customer)
