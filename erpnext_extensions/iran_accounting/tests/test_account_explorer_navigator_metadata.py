# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

import unittest

import frappe

from erpnext_extensions.iran_accounting.account_explorer import api
from erpnext_extensions.iran_accounting.account_explorer.dimension_discovery import get_discovered_dimensions
from erpnext_extensions.iran_accounting.tests.test_account_explorer_fixtures import enable_wave2a_analysis


class TestAccountExplorerNavigatorMetadata(unittest.TestCase):
	def setUp(self):
		enable_wave2a_analysis()
		frappe.set_user("Administrator")
		self.metadata = api.get_metadata()

	def test_account_levels_metadata_contains_only_account_levels(self):
		levels = self.metadata.get("levels") or []
		self.assertTrue(levels)
		for level in levels:
			self.assertIn("sequence", level)
			self.assertIn("code_length", level)
			self.assertNotIn("fieldname", level)
			self.assertNotIn("dimension_type", level)

	def test_dimensions_metadata_is_separated(self):
		dimensions = self.metadata.get("dimensions") or []
		levels = self.metadata.get("levels") or []
		level_sequences = {level["sequence"] for level in levels}
		dimension_fieldnames = {row["fieldname"] for row in dimensions}

		self.assertNotEqual(levels, dimensions)
		for dimension in dimensions:
			self.assertIn("fieldname", dimension)
			self.assertNotIn("sequence", dimension)
			self.assertNotIn("code_length", dimension)

		account_axis = next(row for row in self.metadata.get("axes", []) if row.get("id") == "account_level")
		dimension_axis = next(row for row in self.metadata.get("axes", []) if row.get("id") == "dimension")

		for child in account_axis.get("children") or []:
			self.assertEqual(child.get("nav_kind"), "account_level")
			self.assertIn("sequence", child)
			self.assertNotIn("fieldname", child)

		for child in dimension_axis.get("children") or []:
			self.assertEqual(child.get("nav_kind"), "dimension_type")
			self.assertIn("fieldname", child)
			self.assertNotIn("sequence", child)

		self.assertFalse(level_sequences & dimension_fieldnames)

	def test_no_dimension_type_in_account_level_navigator(self):
		dimensions = get_discovered_dimensions()
		dimension_fieldnames = {row["fieldname"] for row in dimensions}
		dimension_labels = {row.get("label") for row in dimensions if row.get("label")}

		account_axis = next(row for row in self.metadata.get("axes", []) if row.get("id") == "account_level")
		for child in account_axis.get("children") or []:
			fieldname = child.get("fieldname") or child.get("dimension_type")
			self.assertIsNone(fieldname)
			self.assertNotIn(child.get("title"), dimension_labels)
			self.assertNotIn(child.get("title_fa"), dimension_labels)
			for key in ("fieldname", "dimension_type", "document_type"):
				self.assertNotIn(key, child)

		for level in self.metadata.get("levels") or []:
			self.assertNotIn(level.get("title"), dimension_fieldnames)
			self.assertNotIn(level.get("title_fa"), dimension_fieldnames)
