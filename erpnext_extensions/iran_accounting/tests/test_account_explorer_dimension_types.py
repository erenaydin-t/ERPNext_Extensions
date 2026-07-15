# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

import unittest

import frappe

from erpnext_extensions.iran_accounting.account_explorer import api
from erpnext_extensions.iran_accounting.account_explorer.dimension_discovery import (
	filter_usable_gl_dimensions,
	get_discovered_dimensions,
)
from erpnext_extensions.iran_accounting.tests.test_account_explorer_fixtures import (
	build_payload,
	current_fiscal_year,
	enable_wave2a_analysis,
	require_site,
)


class TestAccountExplorerDimensionTypes(unittest.TestCase):
	def setUp(self):
		self.company = require_site(self)
		enable_wave2a_analysis()
		frappe.set_user("Administrator")
		fy = current_fiscal_year(self.company)
		if not fy:
			self.skipTest("No fiscal year")
		self.fiscal_year, self.from_date, self.to_date = fy

	def test_dimension_types_are_separated(self):
		if not frappe.get_meta("GL Entry").has_field("cost_center"):
			self.skipTest("No cost_center on GL Entry")
		cc_payload = build_payload(
			self.company,
			self.fiscal_year,
			self.from_date,
			self.to_date,
			analysis={"view_axis": "dimension", "dimension_scope": {"dimension_type": "cost_center"}},
		)
		cc_result = api.get_dimension_summary(cc_payload)
		cc_values = {row.get("dimension_value") for row in cc_result.get("rows") or [] if row.get("dimension_value")}

		if not frappe.get_meta("GL Entry").has_field("project"):
			self.skipTest("No project on GL Entry")
		project_payload = build_payload(
			self.company,
			self.fiscal_year,
			self.from_date,
			self.to_date,
			analysis={"view_axis": "dimension", "dimension_scope": {"dimension_type": "project"}},
		)
		project_result = api.get_dimension_summary(project_payload)
		project_values = {
			row.get("dimension_value") for row in project_result.get("rows") or [] if row.get("dimension_value")
		}
		self.assertFalse(cc_values & project_values)

	def test_custom_dimension_discovery(self):
		dimensions = get_discovered_dimensions()
		fieldnames = {row["fieldname"] for row in dimensions}
		self.assertIn("cost_center", fieldnames)
		meta = api.get_metadata()
		axis = next((row for row in meta.get("axes", []) if row.get("id") == "dimension"), None)
		self.assertIsNotNone(axis)
		self.assertTrue(axis.get("children"))

	def test_filter_usable_gl_dimensions_drops_missing_fields(self):
		usable = filter_usable_gl_dimensions(
			[
				{"fieldname": "cost_center", "label": "Cost Center", "is_native": 1},
				{"fieldname": "custom_dim_1", "label": "Missing", "is_native": 0},
				{"fieldname": "cost_center", "label": "Dup", "is_native": 1},
			],
			warn=False,
		)
		self.assertEqual([row["fieldname"] for row in usable], ["cost_center"])
		self.assertFalse(frappe.get_meta("GL Entry").has_field("custom_dim_1"))

	def test_discovered_dimensions_only_include_gl_fields(self):
		for row in get_discovered_dimensions():
			self.assertTrue(
				frappe.get_meta("GL Entry").has_field(row["fieldname"]),
				msg=f"discovered dimension missing on GL Entry: {row['fieldname']}",
			)
