# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

import unittest

import frappe

from erpnext_extensions.iran_accounting.account_explorer import api
from erpnext_extensions.iran_accounting.account_explorer.constants import VIRTUAL_DIMENSION_UNSPECIFIED_PREFIX
from erpnext_extensions.iran_accounting.account_explorer.dimension_discovery import not_specified_label
from erpnext_extensions.iran_accounting.tests.test_account_explorer_fixtures import (
	build_payload,
	current_fiscal_year,
	enable_wave2a_analysis,
	require_site,
)


class TestAccountExplorerDimensionSummary(unittest.TestCase):
	def setUp(self):
		self.company = require_site(self)
		enable_wave2a_analysis()
		frappe.set_user("Administrator")
		fy = current_fiscal_year(self.company)
		if not fy:
			self.skipTest("No fiscal year")
		self.fiscal_year, self.from_date, self.to_date = fy

	def test_dimension_summary_requires_field(self):
		payload = build_payload(
			self.company,
			self.fiscal_year,
			self.from_date,
			self.to_date,
			analysis={"view_axis": "dimension", "dimension_scope": {}},
		)
		with self.assertRaises(frappe.ValidationError):
			api.get_dimension_summary(payload)

	def test_dimension_summary_cost_center(self):
		if not frappe.get_meta("GL Entry").has_field("cost_center"):
			self.skipTest("No cost_center on GL Entry")
		payload = build_payload(
			self.company,
			self.fiscal_year,
			self.from_date,
			self.to_date,
			analysis={
				"view_axis": "dimension",
				"dimension_scope": {"dimension_type": "cost_center"},
			},
		)
		result = api.get_dimension_summary(payload)
		self.assertIn("rows", result)
		self.assertEqual(result.get("dimension_type"), "cost_center")

	def test_not_specified_row_label(self):
		payload = build_payload(
			self.company,
			self.fiscal_year,
			self.from_date,
			self.to_date,
			analysis={
				"view_axis": "dimension",
				"dimension_scope": {"dimension_type": "cost_center"},
			},
			document={"hide_zero_rows": 0},
		)
		result = api.get_dimension_summary(payload)
		unspecified = [
			row
			for row in result["rows"]
			if (row.get("row_key") or "").startswith(VIRTUAL_DIMENSION_UNSPECIFIED_PREFIX)
		]
		for row in unspecified:
			self.assertEqual(row["display_title"], not_specified_label())

	def test_dimension_pagination(self):
		payload = build_payload(
			self.company,
			self.fiscal_year,
			self.from_date,
			self.to_date,
			analysis={
				"view_axis": "dimension",
				"dimension_scope": {"dimension_type": "cost_center"},
				"page_size": 1,
				"page": 1,
			},
		)
		result = api.get_dimension_summary(payload)
		self.assertLessEqual(len(result["rows"]), 1)

	def test_dimension_parity_against_gl(self):
		from erpnext_extensions.iran_accounting.account_explorer.dimension_opening import (
			get_dimension_opening_balances,
			get_dimension_period_balances,
		)
		from erpnext_extensions.iran_accounting.account_explorer.query_spec import (
			AccountExplorerQuerySpec_from_client,
		)

		account = frappe.db.get_value("Account", {"company": self.company, "is_group": 0}, "name")
		if not account:
			self.skipTest("No leaf account")
		cc = frappe.db.sql(
			"""
			select distinct cost_center from `tabGL Entry`
			where company=%s and account=%s and ifnull(cost_center,'')!='' and is_cancelled=0
			limit 1
			""",
			(self.company, account),
		)
		if not cc:
			self.skipTest("No cost center GL on account")
		cost_center = cc[0][0]

		payload = build_payload(
			self.company,
			self.fiscal_year,
			self.from_date,
			self.to_date,
			analysis={
				"view_axis": "dimension",
				"dimension_scope": {"dimension_type": "cost_center", "selected_dimension_value": cost_center},
				"account_scope": {"mode": "account", "selected_account": account},
			},
			document={"hide_zero_rows": 0},
		)
		spec = AccountExplorerQuerySpec_from_client(payload, require_dates=True)
		opening = get_dimension_opening_balances(spec, "cost_center").get(cost_center, (0, 0))
		period = get_dimension_period_balances(spec, "cost_center").get(cost_center, (0, 0))
		result = api.get_dimension_summary(payload)
		self.assertEqual(len(result["rows"]), 1)
		row = result["rows"][0]
		self.assertAlmostEqual(row["opening_debit"], opening[0], places=2)
		self.assertAlmostEqual(row["opening_credit"], opening[1], places=2)
		self.assertAlmostEqual(row["period_debit"], period[0], places=2)
		self.assertAlmostEqual(row["period_credit"], period[1], places=2)
