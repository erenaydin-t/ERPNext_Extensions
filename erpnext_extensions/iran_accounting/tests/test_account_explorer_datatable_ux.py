"""Wave 3B-1.5 DataTable summary-grid UX stabilization tests."""

from __future__ import annotations

import os
import unittest

import frappe


class TestAccountExplorerDataTableUX(unittest.TestCase):
	def setUp(self):
		self.app_root = frappe.get_app_path("erpnext_extensions")
		self.page_js = os.path.join(
			self.app_root,
			"erpnext_extensions",
			"page",
			"account_explorer",
			"account_explorer.js",
		)
		self.adapter_js = os.path.join(
			self.app_root,
			"erpnext_extensions",
			"page",
			"account_explorer",
			"adapters",
			"ae_datatable_adapter.js",
		)
		self.css_path = os.path.join(
			self.app_root,
			"erpnext_extensions",
			"page",
			"account_explorer",
			"account_explorer.css",
		)
		with open(self.page_js, encoding="utf-8") as handle:
			self.page_content = handle.read()
		with open(self.adapter_js, encoding="utf-8") as handle:
			self.adapter_content = handle.read()
		with open(self.css_path, encoding="utf-8") as handle:
			self.css_content = handle.read()

	def test_column_width_metadata_mapping(self):
		for fragment in (
			"resolve_column_width_profile",
			"resolve_column_width",
			"AE_DT_WIDTH_PROFILES",
		):
			self.assertIn(fragment, self.adapter_content)

	def test_required_column_cannot_be_hidden(self):
		block = self.page_content.split("show_column_chooser() {", 1)[1].split("\n\t}", 1)[0]
		self.assertIn("get_required_summary_column_id", block)
		self.assertIn("read_only: col.id === required ? 1 : 0", block)

	def test_column_chooser_restore_defaults(self):
		for fragment in (
			"restore_column_defaults",
			"restore_defaults",
			"set_summary_hidden_columns([])",
		):
			self.assertIn(fragment, self.page_content)

	def test_ellipsis_and_tooltip_formatting(self):
		for fragment in (
			"ae-dt-cell-text",
			"title=",
			"aria-label",
			"ae-dt-col--ellipsis",
		):
			self.assertIn(fragment, self.adapter_content)
		self.assertIn("ae-dt-cell-text", self.css_content)

	def test_sticky_first_business_column(self):
		self.assertIn("setColumnSticky(offset, true)", self.adapter_content)
		self.assertIn("checkbox_column === false ? 0 : 1", self.adapter_content)

	def test_selection_count_and_clear(self):
		for fragment in (
			"get_checked_row_count",
			"clear_grid_selection",
			'__("1 row selected")',
			'__("{0} rows selected"',
			"Clear Selection",
		):
			self.assertIn(fragment, self.page_content)
		# Frozen UX contract — never revert to "Selected: {0}".
		self.assertNotIn("Selected: {0}", self.page_content)
		self.assertEqual(self.page_content.count('__("1 row selected")'), 3)
		self.assertGreaterEqual(self.page_content.count('__("{0} rows selected"'), 3)

	def test_selection_clears_on_axis_switch(self):
		start = self.page_content.index("switch_axis(view_axis")
		block = self.page_content[start : start + 400]
		self.assertIn("clear_grid_selection", block)

	def test_selection_clears_on_pagination(self):
		block = self.page_content.split("render_pagination() {", 1)[1].split("\n\t}", 1)[0]
		self.assertIn("clear_grid_selection", block)

	def test_loading_ready_lifecycle(self):
		for fragment in (
			"ae-datatable-skeleton",
			"set_loading",
			"is_interaction_ready",
			"ae-datatable-host--loading",
		):
			self.assertIn(fragment, self.adapter_content)
		self.assertIn("ae-datatable-skeleton", self.css_content)

	def test_empty_and_filtered_states(self):
		for fragment in (
			"render_grid_empty_state",
			"get_grid_empty_reason",
			"No rows match the current Document Scope filters",
			"Clear Advanced Filters",
		):
			self.assertIn(fragment, self.page_content)

	def test_error_state_retry(self):
		start = self.page_content.index("render_grid_empty_state(reason")
		block = self.page_content[start : start + 1400]
		self.assertIn("Account Explorer could not load this view", block)
		self.assertIn("Retry", block)

	def test_sticky_totals_uses_api_totals(self):
		block = self.page_content.split("render_totals() {", 1)[1].split("\n\t}", 1)[0]
		self.assertIn("this.totals", block)
		self.assertIn("ae-totals-bar--sticky", block)

	def test_sort_state_reflects_server_sort(self):
		self.assertIn("sort_field === col.id ? sort_order : \"none\"", self.adapter_content)
		self.assertIn("_suppress_datatable_sort_events", self.page_content)

	def test_density_modes_in_presentation(self):
		self.assertIn("set_grid_density", self.page_content)
		self.assertIn("get_grid_density", self.page_content)
		self.assertIn("density: this.grid_density", self.page_content)
		self.assertIn("set_density", self.adapter_content)

	def test_keyboard_drill_and_copy(self):
		block = self.page_content.split("_bind_grid_keyboard_shortcuts() {", 1)[1].split("\n\t}", 1)[0]
		self.assertIn("ArrowDown", block)
		self.assertIn("Enter", block)
		self.assertIn("handle_summary_row_dblclick", block)
		self.assertIn("copy_row_tsv", block)
		self.assertIn('key === "ArrowLeft"', block)
		self.assertIn("event.altKey", block)

	def test_interactive_controls_do_not_drill(self):
		self.assertIn(".ae-grid-toolbar", self.adapter_content)
		self.assertIn("is_interactive_grid_target", self.adapter_content)

	def test_feature_flag_paths_remain(self):
		for fragment in (
			"is_datatable_summary_enabled",
			"render_legacy_summary_grid",
			"render_datatable_summary_grid",
		):
			self.assertIn(fragment, self.page_content)

	def test_gl_detail_remains_legacy(self):
		start = self.page_content.index("async render_grid(columns")
		block = self.page_content[start : start + 500]
		self.assertIn("grouped_gl", block)
		self.assertIn("render_gl_detail_view", block)

	def test_copy_uses_frappe_clipboard(self):
		for fragment in (
			"copy_to_clipboard",
			"copy_cell_value",
			"copy_row_tsv",
			"copy_checked_rows_tsv",
		):
			self.assertIn(fragment, self.adapter_content)

	def test_no_datatable_in_page_controller(self):
		start = self.page_content.index("render_datatable_summary_grid")
		end = self.page_content.index("is_voucher_analysis_enabled", start)
		block = self.page_content[start:end]
		self.assertNotIn("new DataTable", block)

	def test_incremental_datatable_update_path(self):
		block = self.page_content.split("async render_datatable_summary_grid(columns, generation)", 1)[1]
		block = block.split("\n\tis_voucher_analysis_enabled()", 1)[0]
		self.assertIn("should_datatable_incremental_update", block)
		self.assertIn("datatable_adapter.update(visible, this.rows, options)", block)

	def test_clusterize_enabled_for_large_pages(self):
		self.assertIn("should_clusterize", self.adapter_content)
		self.assertIn("AE_DT_CLUSTERIZE_ROW_THRESHOLD", self.adapter_content)
		block = self.page_content.split("get_datatable_grid_options(visible_columns)", 1)[1].split("\n\t}", 1)[0]
		self.assertIn("clusterize:", block)

	def test_resize_observer_debounced(self):
		self.assertIn("ResizeObserver", self.adapter_content)
		self.assertIn("AE_DT_RESIZE_DEBOUNCE_MS", self.adapter_content)

	def test_skips_redundant_datatable_refresh(self):
		self.assertIn("_build_refresh_signature", self.adapter_content)
		self.assertIn("skipped_refresh", self.adapter_content)

	def test_grid_perf_instrumentation(self):
		for fragment in (
			"begin_grid_perf",
			"end_grid_perf",
			"get_grid_perf_report",
			"get_grid_perf_summary",
			"get_grid_memory_diagnostics",
			"refresh_history",
			"api_elapsed_ms",
			"render_elapsed_ms",
			"_refresh_after_drill",
			"on_page_hide",
			"measure_datatable_stress_row_count",
		):
			self.assertIn(fragment, self.page_content)

	def test_memory_teardown_clears_adapter_state(self):
		block = self.adapter_content.split("_teardown_instance()", 1)[1].split("\n\tdestroy()", 1)[0]
		self.assertIn("_unbind_resize_observer", block)
		self.assertIn("_options = {}", block)
		self.assertIn("_source_rows = []", block)
		self.assertIn("_rows_by_key = new Map()", block)

	def test_lifecycle_leak_diagnostics_api(self):
		for fragment in (
			"get_lifecycle_leak_diagnostics",
			"run_lifecycle_leak_cycle",
			"explorer_store_subscriptions",
			"detached_dom_nodes",
			"reset_grid_lifecycle_counters",
			"get_grid_lifecycle_counters",
			"get_perf_hotspots",
			"measure_datatable_scroll_fps",
		):
			self.assertIn(fragment, self.page_content)
		for fragment in (
			"get_subscriber_count",
			"get_listener_counts",
			"get_active_mount_count",
			"get_detached_host_count",
			"reset_lifecycle_counters",
			"get_lifecycle_counters",
		):
			self.assertIn(
				fragment,
				self.page_content if fragment in ("get_subscriber_count", "get_listener_counts") else self.adapter_content,
			)
