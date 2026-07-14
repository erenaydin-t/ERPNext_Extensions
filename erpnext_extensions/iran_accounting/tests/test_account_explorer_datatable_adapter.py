"""Wave 3B-1 DataTable summary grid adapter and feature flag tests."""

from __future__ import annotations

import os
import re
import unittest

import frappe

from erpnext_extensions.iran_accounting.account_explorer.api import (
	DIMENSION_COLUMNS,
	PARTY_COLUMNS,
	SUMMARY_COLUMNS,
	VOUCHER_COLUMNS,
	get_metadata,
)


class TestAccountExplorerDataTableAdapter(unittest.TestCase):
	def setUp(self):
		self.app_root = frappe.get_app_path("erpnext_extensions")
		self._saved_datatable_flag = int(
			frappe.db.get_value(
				"Iran Accounting Settings",
				"Iran Accounting Settings",
				"account_explorer_datatable_enabled",
			)
			or 0
		)
		frappe.db.set_value(
			"Iran Accounting Settings",
			"Iran Accounting Settings",
			"account_explorer_datatable_enabled",
			0,
		)
		frappe.db.commit()
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

	def tearDown(self):
		frappe.db.set_value(
			"Iran Accounting Settings",
			"Iran Accounting Settings",
			"account_explorer_datatable_enabled",
			self._saved_datatable_flag,
		)
		frappe.db.commit()

	def _read(self, path: str) -> str:
		with open(path, encoding="utf-8") as handle:
			return handle.read()

	def test_feature_flag_defaults_off(self):
		settings = frappe.get_single("Iran Accounting Settings")
		self.assertEqual(int(settings.account_explorer_datatable_enabled or 0), 0)

	def test_metadata_exposes_datatable_flag_default_off(self):
		metadata = get_metadata()
		self.assertIn("account_explorer_datatable_enabled", metadata)
		self.assertEqual(metadata["account_explorer_datatable_enabled"], 0)

	def test_legacy_renderer_hooks_present(self):
		content = self._read(self.page_js)
		for fragment in (
			"render_legacy_summary_grid",
			"is_datatable_summary_enabled",
			"destroy_summary_datatable",
		):
			self.assertIn(fragment, content)

	def test_datatable_renderer_hooks_present(self):
		content = self._read(self.page_js)
		for fragment in (
			"async render_grid",
			"render_datatable_summary_grid",
			"get_datatable_grid_options",
			"datatable_adapter.mount",
			"grid_render_generation",
			"_is_stale_grid_render",
			"is_summary_grid_ready",
		):
			self.assertIn(fragment, content)
		adapter = self._read(self.adapter_js)
		self.assertIn("async update(", adapter)
		self.assertIn("cancel_pending_mount", adapter)
		self.assertIn("resolve_source_row_by_key", adapter)
		self.assertIn("_finalize_mount", adapter)
		self.assertNotIn("MutationObserver", adapter)
		self.assertIn("data-ae-row-key", adapter)

	def test_refresh_summary_uses_inline_loading_not_global_freeze(self):
		content = self._read(self.page_js)
		refresh_block = content.split("async _refresh_summary()", 1)[1].split("\n\t}", 1)[0]
		self.assertNotIn("freeze: true", refresh_block)
		self.assertIn("ae-grid-wrap--loading", content)
		self.assertIn("loading: { summary: true }", refresh_block)

	def test_async_render_contract_waits_before_summary_loaded(self):
		content = self._read(self.page_js)
		refresh_block = content.split("async _refresh_summary()", 1)[1].split("\n\t}", 1)[0]
		self.assertIn("await this.render_grid(data.columns || [], generation)", refresh_block)
		self.assertIn("summary:loaded", refresh_block)
		self.assertIn("_summary_refresh_tail", content)
		render_block = content.split("async render_grid(columns, generation = null)", 1)[1].split("\n\t}", 1)[0]
		self.assertIn("await this.render_datatable_summary_grid(columns, render_generation)", render_block)

	def test_adapter_row_identity_uses_stable_row_key(self):
		adapter = self._read(self.adapter_js)
		for fragment in (
			"_rows_by_key",
			"row_key: row?.row_key",
			"resolve_source_row_by_key",
			"resolve_row_from_event",
			"_sync_row_dom_keys",
			".dt-row:not(.dt-row-header):not(.dt-row-filter)",
		):
			self.assertIn(fragment, adapter)

	def test_interaction_ready_is_read_only(self):
		adapter = self._read(self.adapter_js)
		ready_block = adapter.split("is_interaction_ready()", 1)[1].split("\n\t}", 1)[0]
		self.assertNotIn("_sync_row_dom_keys", ready_block)

	def test_grid_interactions_delegate_from_stable_wrap(self):
		content = self._read(self.page_js)
		for fragment in (
			"_bind_datatable_grid_interactions",
			"should_handle_datatable_row_event",
			"is_interactive_grid_target",
			"resolve_row_from_event",
			"dblclick${this._datatable_grid_namespace}",
		):
			self.assertIn(fragment, content)

	def test_interactive_grid_target_excludes_controls(self):
		adapter = self._read(self.adapter_js)
		for fragment in (
			"is_interactive_grid_target",
			".dt-cell__resize-handle",
			".ae-voucher-action",
			'[type="checkbox"]',
			".dt-row-filter",
		):
			self.assertIn(fragment, adapter)

	def test_datatable_sort_does_not_loop_refresh_on_mount(self):
		content = self._read(self.page_js)
		for fragment in (
			"handle_datatable_server_sort",
			"_suppress_datatable_sort_events",
		):
			self.assertIn(fragment, content)

	def test_voucher_row_key_format_is_stable(self):
		voucher_summary = os.path.join(
			self.app_root,
			"iran_accounting",
			"account_explorer",
			"voucher_summary.py",
		)
		content = self._read(voucher_summary)
		self.assertIn('"row_key": f"voucher:{voucher_type}:{voucher_no}"', content)
		self.assertIn("drill_down_enabled", content)

	def test_gl_detail_remains_legacy_renderer(self):
		content = self._read(self.page_js)
		self.assertRegex(
			content,
			r'detail_mode === "grouped_gl"[\s\S]{0,220}render_gl_detail_view',
		)
		self.assertNotRegex(
			content,
			r'detail_mode === "grouped_gl"[\s\S]{0,220}render_datatable_summary_grid',
		)

	def test_adapter_public_interface(self):
		content = self._read(self.adapter_js)
		for fragment in (
			"async mount(",
			"async update(",
			"destroy()",
			"is_mounted()",
			"get_checked_rows()",
			"clear_selection()",
			"get_column_state()",
			"apply_column_state(",
			"set_loading(",
			"show_empty_state(",
			"map_columns(",
			"map_rows(",
		):
			self.assertIn(fragment, content)

	def test_adapter_is_only_datatable_entry_point(self):
		content = self._read(self.page_js)
		self.assertNotIn("new DataTable", content)
		adapter = self._read(self.adapter_js)
		self.assertIn("new DataTable", adapter)

	def test_account_columns_structure(self):
		ids = [col["id"] for col in SUMMARY_COLUMNS]
		self.assertEqual(
			ids[:4],
			["display_code", "display_title", "period_debit", "period_credit"],
		)
		self.assertTrue(all(col.get("fieldtype") for col in SUMMARY_COLUMNS))

	def test_party_columns_structure(self):
		ids = [col["id"] for col in PARTY_COLUMNS]
		self.assertIn("party_type", ids)
		self.assertIn("display_title", ids)
		self.assertIn("period_debit", ids)

	def test_dimension_columns_structure(self):
		ids = [col["id"] for col in DIMENSION_COLUMNS]
		self.assertIn("display_code", ids)
		self.assertIn("display_title", ids)

	def test_currency_amount_columns_preserve_native_fieldtypes(self):
		for col in SUMMARY_COLUMNS:
			if col["id"] in ("period_debit", "period_credit", "debit_balance", "credit_balance"):
				self.assertEqual(col["fieldtype"], "Currency")

	def test_voucher_row_metadata_columns(self):
		ids = [col["id"] for col in VOUCHER_COLUMNS]
		for field in ("posting_date", "voucher_type", "voucher_no", "scoped_debit", "scoped_credit"):
			self.assertIn(field, ids)

	def test_voucher_gl_module_untouched_by_datatable_wave(self):
		voucher_gl = os.path.join(
			self.app_root,
			"iran_accounting",
			"account_explorer",
			"voucher_gl.py",
		)
		content = self._read(voucher_gl)
		self.assertNotIn("DataTable", content)
		self.assertIn("get_discovered_dimensions", content)

	def test_architecture_foundation_still_present(self):
		content = self._read(self.page_js)
		for fragment in (
			"_init_explorer_architecture",
			"ExplorerStore",
			"on_page_show",
		):
			self.assertIn(fragment, content)
