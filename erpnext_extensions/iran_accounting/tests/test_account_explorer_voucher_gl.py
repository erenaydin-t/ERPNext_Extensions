# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

import unittest
from unittest.mock import patch

import frappe

from erpnext_extensions.iran_accounting.account_explorer import api
from erpnext_extensions.iran_accounting.account_explorer.api import build_gl_detail_columns
from erpnext_extensions.iran_accounting.account_explorer.constants import (
	GL_DIMENSION_EXPAND_THRESHOLD,
	gl_dimension_layout_mode,
)
from erpnext_extensions.iran_accounting.account_explorer.voucher_gl import (
	_gl_detail_sortable_fields,
	_row_dimensions,
)
from erpnext_extensions.iran_accounting.tests.test_account_explorer_fixtures import (
	build_payload,
	current_fiscal_year,
	enable_wave2b_voucher,
	require_site,
)

COST_CENTER_ONLY = [
	{
		"fieldname": "cost_center",
		"label": "Cost Center",
		"label_fa": "مرکز هزینه",
		"document_type": "Cost Center",
		"is_native": 1,
	},
]
COST_CENTER_AND_PROJECT = [
	*COST_CENTER_ONLY,
	{
		"fieldname": "project",
		"label": "Project",
		"label_fa": "پروژه",
		"document_type": "Project",
		"is_native": 1,
	},
]
MULTIPLE_DIMENSIONS = [
	*COST_CENTER_AND_PROJECT,
	{"fieldname": "facility", "label": "Facility", "document_type": "Warehouse", "is_native": 0},
	{"fieldname": "department", "label": "Department", "document_type": "Department", "is_native": 0},
]
MANY_DIMENSIONS = [
	{
		"fieldname": f"custom_dim_{index}",
		"label": f"Dimension {index}",
		"label_fa": f"بُعد {index}",
		"document_type": "Cost Center",
		"is_native": 0,
	}
	for index in range(1, 8)
]


class TestGlDetailDynamicDimensions(unittest.TestCase):
	def test_columns_cost_center_only(self):
		columns = build_gl_detail_columns(COST_CENTER_ONLY)
		column_ids = [column["id"] for column in columns]
		self.assertIn("dimensions", column_ids)
		self.assertIn("dim:cost_center", column_ids)
		self.assertNotIn("dim:project", column_ids)
		self.assertNotIn("dimension_value", column_ids)

	def test_columns_cost_center_and_project(self):
		columns = build_gl_detail_columns(COST_CENTER_AND_PROJECT)
		column_ids = [column["id"] for column in columns]
		self.assertIn("dim:cost_center", column_ids)
		self.assertIn("dim:project", column_ids)

	def test_columns_custom_accounting_dimension(self):
		columns = build_gl_detail_columns(MULTIPLE_DIMENSIONS)
		facility_column = next(column for column in columns if column["id"] == "dim:facility")
		self.assertEqual(facility_column["label"], "Facility")
		self.assertEqual(facility_column["dimension_fieldname"], "facility")
		self.assertEqual(facility_column["column_kind"], "dimension")

	def test_compact_column_avoids_generic_dimensions_label(self):
		columns = build_gl_detail_columns(COST_CENTER_AND_PROJECT)
		compact = next(column for column in columns if column["id"] == "dimensions")
		self.assertEqual(compact["column_kind"], "dimensions_compact")
		self.assertNotEqual(compact["label"], "Dimensions")
		self.assertFalse(compact["label"])
		self.assertEqual(compact["label_key"], "Accounting Dimension Details")

	def test_compact_column_rtl_accessibility_metadata(self):
		columns = build_gl_detail_columns(COST_CENTER_ONLY)
		compact = next(column for column in columns if column["id"] == "dimensions")
		self.assertTrue(compact.get("label_key"))
		cost_center_column = next(column for column in columns if column["id"] == "dim:cost_center")
		self.assertEqual(cost_center_column.get("label_fa"), "مرکز هزینه")

	def test_dimension_layout_mode_expanded_when_few_dimensions(self):
		self.assertEqual(gl_dimension_layout_mode(5, True), "expanded")
		self.assertEqual(gl_dimension_layout_mode(4, True), "expanded")
		self.assertEqual(gl_dimension_layout_mode(5, False), "compact")

	def test_dimension_layout_mode_selector_when_many_dimensions(self):
		self.assertEqual(
			gl_dimension_layout_mode(GL_DIMENSION_EXPAND_THRESHOLD + 1, True),
			"compact_with_selector",
		)
		self.assertEqual(gl_dimension_layout_mode(len(MANY_DIMENSIONS), False), "compact_with_selector")

	def test_row_dimensions_missing_value(self):
		payload = _row_dimensions(
			COST_CENTER_AND_PROJECT,
			{"cost_center": "Main - TC", "project": ""},
			{"cost_center": {"Main - TC": "Main - TC"}, "project": {}},
		)
		self.assertEqual(payload["cost_center"]["value"], "Main - TC")
		self.assertEqual(payload["cost_center"]["label"], "Cost Center")
		self.assertEqual(payload["cost_center"]["label_fa"], "مرکز هزینه")
		self.assertEqual(payload["project"]["value"], "")
		self.assertEqual(payload["project"]["title"], "")

	def test_row_dimensions_labels_and_empty_display(self):
		payload = _row_dimensions(
			MULTIPLE_DIMENSIONS,
			{
				"cost_center": "CC-1",
				"project": "PROJ-1",
				"facility": "FAC-1",
				"department": "",
			},
			{
				"cost_center": {"CC-1": "Sales"},
				"project": {"PROJ-1": "ERP Implementation"},
				"facility": {"FAC-1": "Factory 1"},
				"department": {},
			},
		)
		self.assertEqual(payload["cost_center"]["title"], "Sales")
		self.assertEqual(payload["cost_center"]["label"], "Cost Center")
		self.assertEqual(payload["project"]["title"], "ERP Implementation")
		self.assertEqual(payload["facility"]["title"], "Factory 1")
		self.assertEqual(payload["department"]["value"], "")
		self.assertEqual(payload["department"]["title"], "")

	def test_many_dimensions_builds_all_dynamic_columns(self):
		columns = build_gl_detail_columns(MANY_DIMENSIONS)
		dimension_column_ids = [
			column["id"] for column in columns if column.get("column_kind") == "dimension"
		]
		self.assertEqual(len(dimension_column_ids), len(MANY_DIMENSIONS))
		self.assertIn("dim:custom_dim_6", dimension_column_ids)

	def test_sortable_fields_include_dynamic_dimensions(self):
		sortable = _gl_detail_sortable_fields(MULTIPLE_DIMENSIONS)
		self.assertIn("dim:facility", sortable)
		self.assertIn("dim:department", sortable)

	@patch("erpnext_extensions.iran_accounting.account_explorer.voucher_gl.get_discovered_dimensions")
	def test_grouped_gl_response_dimensions_metadata(self, mock_discovered):
		mock_discovered.return_value = COST_CENTER_AND_PROJECT
		company = require_site(self)
		if not company:
			self.skipTest("ERPNext _Test Company not available")
		enable_wave2b_voucher()
		frappe.set_user("Administrator")
		fy = current_fiscal_year(company)
		if not fy:
			self.skipTest("No fiscal year")
		fiscal_year, from_date, to_date = fy
		sample = frappe.db.get_value(
			"GL Entry",
			{"company": company, "is_cancelled": 0},
			["voucher_type", "voucher_no"],
			as_dict=True,
		)
		if not sample:
			self.skipTest("No GL Entry data")
		payload = build_payload(
			company,
			fiscal_year,
			from_date,
			to_date,
			analysis={
				"view_axis": "voucher",
				"detail_mode": "grouped_gl",
				"voucher_scope": {
					"voucher_type": sample.voucher_type,
					"voucher_no": sample.voucher_no,
				},
			},
		)
		result = api.get_grouped_gl_entries(payload)
		self.assertEqual(
			[field["fieldname"] for field in result["dimensions"]],
			["cost_center", "project"],
		)
		self.assertEqual(result["gl_dimension_expand_threshold"], GL_DIMENSION_EXPAND_THRESHOLD)
		self.assertEqual(result["gl_dimension_layout"], "compact")
		column_ids = [column["id"] for column in result["columns"]]
		self.assertIn("dimensions", column_ids)
		self.assertIn("dim:cost_center", column_ids)
		self.assertIn("dim:project", column_ids)
		for row in result["rows"]:
			self.assertIn("dimensions", row)
			self.assertIn("cost_center", row["dimensions"])
			self.assertIn("project", row["dimensions"])
			self.assertIn("dim:cost_center", row)

	@patch("erpnext_extensions.iran_accounting.account_explorer.voucher_gl.get_discovered_dimensions")
	def test_grouped_gl_many_dimensions_uses_selector_layout(self, mock_discovered):
		mock_discovered.return_value = MANY_DIMENSIONS
		company = require_site(self)
		if not company:
			self.skipTest("ERPNext _Test Company not available")
		enable_wave2b_voucher()
		frappe.set_user("Administrator")
		fy = current_fiscal_year(company)
		if not fy:
			self.skipTest("No fiscal year")
		fiscal_year, from_date, to_date = fy
		sample = frappe.db.get_value(
			"GL Entry",
			{"company": company, "is_cancelled": 0},
			["voucher_type", "voucher_no"],
			as_dict=True,
		)
		if not sample:
			self.skipTest("No GL Entry data")
		payload = build_payload(
			company,
			fiscal_year,
			from_date,
			to_date,
			analysis={
				"view_axis": "voucher",
				"detail_mode": "grouped_gl",
				"voucher_scope": {
					"voucher_type": sample.voucher_type,
					"voucher_no": sample.voucher_no,
				},
			},
		)
		result = api.get_grouped_gl_entries(payload)
		self.assertEqual(result["gl_dimension_layout"], "compact_with_selector")
		self.assertEqual(len(result["dimensions"]), len(MANY_DIMENSIONS))


class TestAccountExplorerVoucherGl(unittest.TestCase):
	def setUp(self):
		self.company = require_site(self)
		enable_wave2b_voucher()
		frappe.set_user("Administrator")
		fy = current_fiscal_year(self.company)
		if not fy:
			self.skipTest("No fiscal year")
		self.fiscal_year, self.from_date, self.to_date = fy
		self.sample = frappe.db.get_value(
			"GL Entry",
			{"company": self.company, "is_cancelled": 0},
			["voucher_type", "voucher_no"],
			as_dict=True,
		)
		if not self.sample:
			self.skipTest("No GL Entry data")
		self.multi_row_voucher = frappe.db.sql(
			"""
			SELECT voucher_type, voucher_no, COUNT(*) AS entry_count
			FROM `tabGL Entry`
			WHERE company = %s AND is_cancelled = 0
			GROUP BY voucher_type, voucher_no
			HAVING entry_count > 1
			ORDER BY entry_count DESC
			LIMIT 1
			""",
			self.company,
			as_dict=True,
		)
		self.multi_row_voucher = self.multi_row_voucher[0] if self.multi_row_voucher else None

	def _grouped_gl_payload(self, voucher_type, voucher_no, **analysis_overrides):
		analysis = {
			"view_axis": "voucher",
			"detail_mode": "grouped_gl",
			"voucher_scope": {
				"voucher_type": voucher_type,
				"voucher_no": voucher_no,
			},
		}
		analysis.update(analysis_overrides)
		return build_payload(
			self.company,
			self.fiscal_year,
			self.from_date,
			self.to_date,
			analysis=analysis,
		)

	def test_grouped_gl_structure(self):
		payload = self._grouped_gl_payload(self.sample.voucher_type, self.sample.voucher_no)
		result = api.get_grouped_gl_entries(payload)
		self.assertIn("rows", result)
		self.assertIn("voucher_header", result)
		self.assertIn("dimensions", result)
		self.assertIn("debit", result["totals"])
		self.assertIn("credit", result["totals"])
		self.assertIn("pagination", result)
		compact_column = next(column for column in result["columns"] if column["id"] == "dimensions")
		self.assertEqual(compact_column["column_kind"], "dimensions_compact")
		self.assertFalse(compact_column["label"])
		for row in result["rows"]:
			self.assertIn("account", row)
			self.assertIn("posting_date", row)
			self.assertIn("dimensions", row)
			self.assertIsInstance(row["dimensions"], dict)
			for dimension in result["dimensions"]:
				fieldname = dimension["fieldname"]
				self.assertIn(fieldname, row["dimensions"])
				self.assertIn("value", row["dimensions"][fieldname])
				self.assertIn("title", row["dimensions"][fieldname])
				self.assertIn("label", row["dimensions"][fieldname])
			self.assertIn("currency", row)
			self.assertIn("remarks", row)
			self.assertIn("debit", row)
			self.assertIn("credit", row)
			self.assertIn("side", row)

	def test_grouped_gl_voucher_header_totals(self):
		payload = self._grouped_gl_payload(self.sample.voucher_type, self.sample.voucher_no)
		result = api.get_grouped_gl_entries(payload)
		header = result["voucher_header"]
		self.assertEqual(header["voucher_type"], self.sample.voucher_type)
		self.assertEqual(header["voucher_no"], self.sample.voucher_no)
		self.assertEqual(header["total_debit"], result["totals"]["debit"])
		self.assertEqual(header["total_credit"], result["totals"]["credit"])

	def test_grouped_gl_supports_multiple_rows_per_voucher(self):
		if not self.multi_row_voucher:
			self.skipTest("No voucher with multiple GL rows")
		payload = self._grouped_gl_payload(
			self.multi_row_voucher.voucher_type,
			self.multi_row_voucher.voucher_no,
		)
		result = api.get_grouped_gl_entries(payload)
		self.assertGreaterEqual(result["pagination"]["total_rows"], 2)
		self.assertGreaterEqual(len(result["rows"]), 1)
		self.assertLessEqual(len(result["rows"]), result["pagination"]["page_size"])

	def test_grouped_gl_pagination(self):
		if not self.multi_row_voucher:
			self.skipTest("No voucher with multiple GL rows")
		payload = self._grouped_gl_payload(
			self.multi_row_voucher.voucher_type,
			self.multi_row_voucher.voucher_no,
			page=1,
			page_size=1,
		)
		result = api.get_grouped_gl_entries(payload)
		self.assertEqual(result["pagination"]["page"], 1)
		self.assertEqual(result["pagination"]["page_size"], 1)
		self.assertEqual(len(result["rows"]), 1)
		if result["pagination"]["total_rows"] > 1:
			self.assertTrue(result["pagination"]["has_next"])
			payload_page_2 = self._grouped_gl_payload(
				self.multi_row_voucher.voucher_type,
				self.multi_row_voucher.voucher_no,
				page=2,
				page_size=1,
			)
			page_2 = api.get_grouped_gl_entries(payload_page_2)
			self.assertEqual(page_2["pagination"]["page"], 2)
			self.assertNotEqual(result["rows"][0]["row_key"], page_2["rows"][0]["row_key"])

	def test_grouped_gl_requires_voucher_scope(self):
		payload = build_payload(
			self.company,
			self.fiscal_year,
			self.from_date,
			self.to_date,
			analysis={"view_axis": "voucher", "detail_mode": "grouped_gl", "voucher_scope": {}},
		)
		with self.assertRaises(frappe.ValidationError):
			api.get_grouped_gl_entries(payload)
