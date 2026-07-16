"""Account Explorer analysis path / breadcrumb navigation UX tests."""

from __future__ import annotations

import os
import unittest

import frappe


class TestAccountExplorerBreadcrumbNavigation(unittest.TestCase):
	def setUp(self):
		self.page_js = os.path.join(
			frappe.get_app_path("erpnext_extensions"),
			"erpnext_extensions",
			"page",
			"account_explorer",
			"account_explorer.js",
		)
		with open(self.page_js, encoding="utf-8") as handle:
			self.content = handle.read()

	def test_analysis_path_orders_axis_before_scopes(self):
		block = self.content.split("build_analysis_path_segments()", 1)[1].split("\n\t}", 1)[0]
		axis_pos = block.find('step: "axis"')
		scope_pos = block.find('step: `scope:${index}`')
		self.assertNotEqual(axis_pos, -1)
		self.assertNotEqual(scope_pos, -1)
		self.assertLess(axis_pos, scope_pos)
		self.assertNotIn('step: "view"', block)

	def test_scope_trail_is_store_synchronized(self):
		for fragment in (
			"sync_scope_trail_from_store",
			"get_scope_trail",
			"get_path_source_axis",
			"remove_scope_at",
			"navigate_to_axis_root",
			"ae-breadcrumb-remove",
		):
			self.assertIn(fragment, self.content)

	def test_reset_analysis_clears_context_only(self):
		start = self.content.index("reset_analysis(refresh = true)")
		reset_block = self.content[start : start + 1200]
		self.assertIn("_reset_breadcrumbs([])", reset_block)
		self.assertIn("account_scope", reset_block)
		self.assertNotIn("document_scope = ae_default_document_scope", reset_block)

	def test_reset_document_scope_does_not_reset_analysis(self):
		start = self.content.index("reset_document_scope() {")
		reset_block = self.content[start : start + 900]
		self.assertIn("document_scope = ae_default_document_scope", reset_block)
		self.assertNotIn("reset_analysis(", reset_block)
		self.assertNotIn("_reset_breadcrumbs", reset_block)

	def test_breadcrumb_remove_uses_accessible_button(self):
		start = self.content.index("render_breadcrumb_segment($item, segment)")
		render_block = self.content[start : start + 900]
		self.assertIn("ae-breadcrumb-remove", render_block)
		self.assertIn("aria-label", render_block)
		self.assertIn("preventDefault", render_block)
		self.assertIn("stopPropagation", render_block)

	def test_go_back_truncates_one_scope_level(self):
		start = self.content.index("go_back() {")
		block = self.content[start : start + 1400]
		self.assertIn("get_scope_trail().slice(0, -1)", block)

	def test_navigate_to_scope_truncates_children(self):
		start = self.content.index("navigate_to_path_step(segment)")
		block = self.content[start : start + 800]
		self.assertIn("scope_trail.slice(0, segment.scope_index + 1)", block)

	def test_remove_scope_at_truncates_target_and_children(self):
		start = self.content.index("remove_scope_at(scope_index)")
		block = self.content[start : start + 500]
		self.assertIn("scope_trail.slice(0, scope_index)", block)

	def test_company_segment_is_not_removable(self):
		block = self.content.split("build_analysis_path_segments()", 1)[1].split("\n\t}", 1)[0]
		company_block = block.split('step: "axis"', 1)[0]
		self.assertIn('step: "company"', company_block)
		self.assertIn("removable: false", company_block)

	def test_go_back_from_gl_detail_returns_to_voucher_summary(self):
		start = self.content.index("go_back() {")
		block = self.content[start : start + 400]
		self.assertIn('detail_mode === "grouped_gl"', block)
		self.assertIn('detail_mode = "summary"', block)

	def test_no_datatable_in_breadcrumb_code(self):
		start = self.content.index("build_analysis_path_segments()")
		end = self.content.index("get_breadcrumb_chip_key(chip)", start)
		breadcrumb_region = self.content[start:end]
		self.assertNotIn("new DataTable", breadcrumb_region)
		self.assertNotIn("AEDataTableAdapter", breadcrumb_region)
