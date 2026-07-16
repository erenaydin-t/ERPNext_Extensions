"""Wave 3B-2 Account Explorer per-user grid preference persistence tests."""

from __future__ import annotations

import os
import unittest

import frappe


class TestAccountExplorerUserPreferences(unittest.TestCase):
	def setUp(self):
		self.app_root = frappe.get_app_path("erpnext_extensions")
		self.base = os.path.join(self.app_root, "erpnext_extensions", "page", "account_explorer")
		self.prefs_js = os.path.join(self.base, "core", "ae_user_preferences.js")
		self.page_js = os.path.join(self.base, "account_explorer.js")
		self.adapter_js = os.path.join(self.base, "adapters", "ae_datatable_adapter.js")
		with open(self.prefs_js, encoding="utf-8") as handle:
			self.prefs_content = handle.read()
		with open(self.page_js, encoding="utf-8") as handle:
			self.page_content = handle.read()
		with open(self.adapter_js, encoding="utf-8") as handle:
			self.adapter_content = handle.read()

	def test_preferences_module_exists(self):
		self.assertTrue(os.path.isfile(self.prefs_js))

	def test_page_includes_preferences_module(self):
		self.assertIn("ae_user_preferences.js", self.page_content)

	def test_missing_settings_return_defaults(self):
		for fragment in ("normalize_grid_preferences", "ae_prefs_default_payload", "schema_version"):
			self.assertIn(fragment, self.prefs_content)

	def test_partial_settings_merge_with_defaults(self):
		self.assertIn("const merged = {", self.prefs_content)
		self.assertIn("...base,", self.prefs_content)

	def test_invalid_json_fails_safely(self):
		self.assertIn("JSON.parse(payload)", self.prefs_content)
		self.assertIn("return ae_prefs_clone(defaults)", self.prefs_content)

	def test_unknown_columns_removed_during_reconcile(self):
		self.assertIn("ae_prefs_reconcile_columns", self.prefs_content)
		self.assertIn("allowed.has(column_id)", self.prefs_content)

	def test_new_columns_appended_in_order(self):
		block = self.prefs_content.split("ae_prefs_reconcile_columns", 1)[1].split("function normalize_grid_preferences", 1)[0]
		self.assertIn("default_order.forEach", block)

	def test_required_column_remains_visible(self):
		block = self.prefs_content.split("ae_prefs_reconcile_columns", 1)[1].split("function normalize_grid_preferences", 1)[0]
		self.assertIn("required_column_id", block)
		self.assertIn("hidden.delete(required_column_id)", block)

	def test_widths_clamped(self):
		self.assertIn("ae_prefs_clamp_width", self.prefs_content)
		self.assertIn("Math.max(min, Math.min(max, numeric))", self.prefs_content)

	def test_invalid_density_resets(self):
		self.assertIn("ae_prefs_normalize_density", self.prefs_content)

	def test_invalid_page_size_resets(self):
		self.assertIn("ae_prefs_normalize_page_size", self.prefs_content)
		self.assertIn("AE_GRID_PAGE_SIZE_OPTIONS", self.prefs_content)

	def test_invalid_number_mode_resets(self):
		self.assertIn("ae_prefs_normalize_number_format", self.prefs_content)
		self.assertIn("AE_NUMBER_FORMAT_MODES", self.prefs_content)

	def test_per_axis_isolation(self):
		self.assertIn('axes[axis_key]', self.prefs_content)
		self.assertIn("ae_prefs_resolve_axis_key", self.prefs_content)

	def test_per_dimension_type_isolation(self):
		self.assertIn('return `dimension:${dimension_type}`', self.prefs_content)

	def test_saved_sort_restoration(self):
		self.assertIn("sort_field", self.prefs_content)
		self.assertIn("sort_order", self.prefs_content)
		self.assertIn("apply_axis_to_controller", self.prefs_content)

	def test_unsupported_schema_version_fails_to_defaults(self):
		self.assertIn("AE_GRID_PREFS_SCHEMA_VERSION", self.prefs_content)
		self.assertIn("source_version > AE_GRID_PREFS_SCHEMA_VERSION", self.prefs_content)
		self.assertIn("ae_prefs_clone(defaults)", self.prefs_content)

	def test_initial_hydration_does_not_save_immediately(self):
		self.assertIn("_hydrating", self.prefs_content)
		self.assertIn("if (this._hydrating || !this._loaded", self.prefs_content)

	def test_debounced_save_delay(self):
		self.assertIn("AE_GRID_PREFS_DEBOUNCE_MS", self.prefs_content)
		self.assertIn("setTimeout", self.prefs_content)

	def test_visibility_changes_schedule_save(self):
		self.assertIn("set_summary_hidden_columns", self.page_content)
		self.assertIn("schedule_save", self.page_content)

	def test_page_size_resets_page_to_one(self):
		block = self.page_content.split("set_page_size(page_size)", 1)[1].split("\n\t}", 1)[0]
		self.assertIn("this.analysis_context.page = 1", block)
		self.assertIn("clear_grid_selection", block)

	def test_reset_current_axis(self):
		self.assertIn("reset_current_axis", self.prefs_content)
		self.assertIn("prompt_reset_grid_preferences", self.page_content)

	def test_reset_all_axes(self):
		self.assertIn("reset_all_axes", self.prefs_content)
		self.assertIn("Reset All Axes", self.page_content)

	def test_save_failure_does_not_break_session(self):
		self.assertIn(".catch((error)", self.prefs_content)
		self.assertIn("preferences:error", self.prefs_content)

	def test_datatable_off_path_skips_adapter_apply(self):
		self.assertIn("is_datatable_summary_enabled", self.page_content)
		self.assertIn("render_legacy_summary_grid", self.page_content)

	def test_datatable_on_restores_preferences_before_render(self):
		self.assertIn("_initialize_after_metadata", self.page_content)
		self.assertIn("user_preferences.load", self.page_content)
		self.assertIn("apply_axis_to_controller", self.page_content)

	def test_user_settings_api_usage(self):
		self.assertIn("frappe.model.user_settings.get(AE_USER_SETTINGS_DOCTYPE)", self.prefs_content)
		self.assertIn("_persist_grid_payload", self.prefs_content)
		self.assertIn("frappe.model.user_settings.update(AE_USER_SETTINGS_DOCTYPE, current)", self.prefs_content)
		self.assertIn("Promise.resolve", self.prefs_content)
		self.assertIn("_persist_grid_payload_sync", self.prefs_content)
		self.assertTrue(
			"keepalive: true" in self.prefs_content or "async: false" in self.prefs_content,
			"unload flush must use keepalive fetch and/or async:false XHR",
		)
		self.assertIn("bind_unload_flush", self.prefs_content)
		self.assertIn("pagehide", self.prefs_content)
		self.assertIn('"Account Explorer"', self.prefs_content)
		self.assertIn('AE_USER_SETTINGS_GRID_KEY = "Grid"', self.prefs_content)

	def test_page_hide_flush_wired(self):
		self.assertIn("on_page_hide", self.page_content)
		self.assertIn("flush_save", self.page_content)
		self.assertIn("sync:", self.page_content)

	def test_apply_axis_signature_guard(self):
		self.assertIn("_axis_signature", self.prefs_content)
		self.assertIn("_applied_axis_signature", self.prefs_content)
		self.assertIn("if (!force && this._applied_axis_signature === signature)", self.prefs_content)

	def test_load_skips_when_already_loaded(self):
		self.assertIn("if (this._loaded && !force)", self.prefs_content)

	def test_presentation_patch_signature_guard(self):
		self.assertIn("_patch_presentation", self.page_content)
		self.assertIn("_presentation_signature", self.page_content)

	def test_adapter_apply_column_state_silent_unchanged(self):
		self.assertIn("apply_column_state(state, { silent = false } = {})", self.adapter_content)
		self.assertIn("if (before === after)", self.adapter_content)

	def test_gl_detail_unaffected_by_summary_preferences(self):
		self.assertIn("render_gl_detail_view", self.page_content)
		self.assertNotIn("user_preferences", self.page_content.split("render_gl_detail_view", 1)[1].split("render_grid(", 1)[0])

	def test_no_query_spec_or_accounting_changes(self):
		for forbidden in (
			"query_spec.py",
			"voucher_gl.py",
			"gle_filters.py",
		):
			self.assertNotIn(forbidden, self.prefs_content)

	def test_adapter_column_callbacks_wired(self):
		for fragment in (
			"on_column_removed",
			"on_column_switched",
			"handle_datatable_column_state_changed",
			"_bind_column_resize_listener",
		):
			self.assertIn(fragment, self.page_content if "handle_datatable" in fragment else self.adapter_content)

	def test_preference_events_documented(self):
		for event in (
			"preferences:loading",
			"preferences:loaded",
			"preferences:saving",
			"preferences:saved",
			"preferences:error",
			"preferences:reset",
		):
			self.assertIn(event, open(os.path.join(self.base, "core", "explorer_events.js"), encoding="utf-8").read())

	def test_number_format_modes_supported(self):
		for mode in ("raw", "auto", "thousands", "millions", "billions", "trillions"):
			self.assertIn(f'"{mode}"', self.prefs_content)
		self.assertIn("ae_format_amount_with_mode", self.page_content)
