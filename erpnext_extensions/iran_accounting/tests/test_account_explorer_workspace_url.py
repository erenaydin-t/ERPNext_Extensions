"""Wave 3B-3 workspace URL / deep-link contract tests."""

from __future__ import annotations

import os
import re
import unittest

import frappe


class TestAccountExplorerWorkspaceUrl(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		app_root = frappe.get_app_path("erpnext_extensions")
		base = os.path.join(app_root, "erpnext_extensions", "page", "account_explorer", "core")
		cls.ws_path = os.path.join(base, "explorer_workspace_state.js")
		cls.codec_path = os.path.join(base, "explorer_workspace_codec.js")
		cls.tokens_path = os.path.join(base, "explorer_workspace_tokens.js")
		cls.page_path = os.path.join(
			app_root,
			"erpnext_extensions",
			"page",
			"account_explorer",
			"account_explorer.js",
		)
		cls.events_path = os.path.join(base, "explorer_events.js")
		with open(cls.ws_path, encoding="utf-8") as handle:
			cls.ws = handle.read()
		with open(cls.codec_path, encoding="utf-8") as handle:
			cls.codec = handle.read()
		with open(cls.tokens_path, encoding="utf-8") as handle:
			cls.tokens = handle.read()
		with open(cls.page_path, encoding="utf-8") as handle:
			cls.page = handle.read()
		with open(cls.events_path, encoding="utf-8") as handle:
			cls.events = handle.read()
		cls.state_src = cls.ws
		cls.ws = cls.codec + "\n" + cls.tokens + "\n" + cls.state_src

	def test_module_size_within_hard_limit(self):
		self.assertLessEqual(self.state_src.count("\n") + 1, 800)
		self.assertLessEqual(self.codec.count("\n") + 1, 800)
		self.assertLessEqual(self.tokens.count("\n") + 1, 400)

	def test_url_schema_version(self):
		self.assertIn("AE_URL_VERSION = 2", self.codec)
		self.assertIn("AE_URL_VERSION_LEGACY = 1", self.codec)
		self.assertIn('AE_URL_VERSION_KEY = "ae_v"', self.codec)
		self.assertIn('AE_URL_STATE_TOKEN_KEY = "ae_state"', self.codec)
		self.assertIn("AE_URL_MAX_LENGTH = 1800", self.codec)
		self.assertIn('"af"', self.codec)

	def test_readable_params_present(self):
		for key in (
			"company",
			"from_date",
			"to_date",
			"axis",
			"level",
			"detail",
			"account",
			"party_type",
			"party",
			"dimension_type",
			"currency_type",
			"voucher_type",
			"voucher_no",
			"page",
			"sort",
			"order",
			"dims",
		):
			self.assertIn(f'"{key}"', self.codec)

	def test_grid_preferences_not_serialized(self):
		banned = ("density", "number_format", "column_widths", "hidden_columns", "column_order")
		# workspace_to_params should not put Grid preference keys
		block = self.ws.split("workspace_to_params", 1)[1].split("params_to_workspace", 1)[0]
		for key in banned:
			self.assertNotIn(f'put("{key}"', block)
			self.assertNotIn(f'params.set("{key}"', block)

	def test_api_surface(self):
		for fragment in (
			"capture_workspace",
			"workspace_to_params",
			"params_to_workspace",
			"validate_workspace",
			"hydrate_from_location",
			"schedule_url_update",
			"write_url",
			"copy_workspace_link",
			"save_compact_token",
			"restore_from_compact_token",
			"exceeds_url_limit",
			"bind_controller",
			"history.replaceState",
			"history.pushState",
			"popstate",
		):
			self.assertIn(fragment, self.ws)

	def test_debounce_and_history_policy(self):
		self.assertIn("AE_URL_DEBOUNCE_MS = 250", self.ws)
		self.assertIn("replaceState", self.ws)
		self.assertIn("pushState", self.ws)

	def test_token_uses_user_settings_not_doctype(self):
		self.assertIn('AE_WORKSPACE_SETTINGS_SECTION = "Workspace"', self.ws)
		self.assertIn("frappe.model.user_settings", self.ws)
		self.assertNotIn("frappe.db.insert", self.ws)
		self.assertNotIn("new frappe.ui.Dialog", self.ws)

	def test_token_bounded(self):
		self.assertIn("AE_WORKSPACE_TOKEN_LIMIT", self.ws)

	def test_stable_param_order(self):
		self.assertIn("AE_PARAM_ORDER", self.ws)
		self.assertIn("ordered_params", self.ws)

	def test_multi_select_and_dims_encoding(self):
		self.assertIn("encode_list", self.ws)
		self.assertIn("decode_list", self.ws)
		self.assertIn('put("dims"', self.ws)

	def test_invalid_axis_and_dimension_discarded(self):
		self.assertIn("Axis {0} is not available and was discarded", self.ws)
		self.assertIn("Dimension {0} is not available and was discarded", self.ws)
		self.assertIn("Sort field {0} is not allowed and was discarded", self.ws)

	def test_corrupt_state_fails_safely(self):
		self.assertIn("Corrupt workspace URL state was ignored", self.ws)
		self.assertIn("Workspace link token was missing or expired", self.ws)

	def test_controller_hydration_sequence(self):
		self.assertIn("await this.user_preferences.load()", self.page)
		self.assertIn("hydrate_from_location", self.page)
		self.assertIn("Copy Workspace Link", self.page)
		self.assertIn("schedule_workspace_url_update", self.page)
		# prefs load before URL hydrate
		prefs_idx = self.page.index("await this.user_preferences.load()")
		hydrate_idx = self.page.index("hydrate_from_location")
		self.assertLess(prefs_idx, hydrate_idx)

	def test_url_updates_on_navigation(self):
		self.assertIn("schedule_workspace_url_update({ push: true })", self.page)
		self.assertIn("schedule_workspace_url_update({ push: false })", self.page)

	def test_voucher_copy_link_preserved(self):
		self.assertIn("copy_gl_detail_link", self.page)
		self.assertIn("include_copy_link", self.page)

	def test_event_bus_documents_workspace_events(self):
		for event_name in (
			"workspace:hydrating",
			"workspace:hydrated",
			"workspace:changed",
			"workspace:url_updated",
			"workspace:error",
			"workspace:token_loaded",
		):
			self.assertIn(event_name, self.events)

	def test_no_accounting_backend_touched(self):
		backend_root = os.path.join(
			frappe.get_app_path("erpnext_extensions"),
			"iran_accounting",
			"account_explorer",
		)
		forbidden = (
			"query_spec.py",
			"schemas.py",
			"gle_filters.py",
			"voucher_gl.py",
			"export.py",
			"opening_balance.py",
		)
		# This wave must not modify these files; assert they still exist and
		# workspace module does not import them by name.
		for name in forbidden:
			path = os.path.join(backend_root, name)
			self.assertTrue(os.path.isfile(path), name)
			self.assertNotIn(name, self.ws)

	def test_page_size_not_forced_into_url_as_grid_pref(self):
		# page is analytical paging; page_size remains User Settings presentation.
		block = self.ws.split("workspace_to_params", 1)[1].split("params_to_workspace", 1)[0]
		self.assertNotIn('put("page_size"', block)

	def test_recursive_update_guard(self):
		self.assertIn("this._updating_url", self.ws)
		self.assertIn("this._hydrating", self.ws)
		self.assertIn("_last_url_signature", self.ws)

	def test_canonical_date_helper(self):
		self.assertIn("canonical_date", self.ws)
		self.assertIn(r"^\d{4}-\d{2}-\d{2}$", self.ws)

	def test_include_workspace_module_in_page(self):
		self.assertIn(
			'{% include "erpnext_extensions/erpnext_extensions/page/account_explorer/core/explorer_workspace_codec.js" %}',
			self.page,
		)
		self.assertIn(
			'{% include "erpnext_extensions/erpnext_extensions/page/account_explorer/core/explorer_workspace_tokens.js" %}',
			self.page,
		)
		self.assertIn(
			'{% include "erpnext_extensions/erpnext_extensions/page/account_explorer/core/explorer_workspace_state.js" %}',
			self.page,
		)

	def test_datatable_off_path_unaffected_by_url_module(self):
		# URL module must not require DataTable for hydrate/serialize
		self.assertNotIn("DataTable", self.ws)
		self.assertNotIn("datatable_adapter", self.ws)

	def test_gl_detail_detail_mode_supported(self):
		self.assertIn("grouped_gl", self.ws)
		self.assertIn('put("detail"', self.ws)

	def test_saved_view_param_supported(self):
		self.assertIn('put("saved_view"', self.ws)
		self.assertIn("_pending_saved_view_from_url", self.page)

	def test_defaults_omitted_axis_and_order(self):
		self.assertIn("AE_DEFAULT_AXIS", self.ws)
		self.assertIn("AE_DEFAULT_SORT_ORDER", self.ws)
		self.assertIn("axis !== AE_DEFAULT_AXIS", self.ws)

	def test_long_url_triggers_token(self):
		self.assertIn("exceeds_url_limit", self.ws)
		self.assertIn("save_compact_token", self.ws)
		self.assertIn("AE_URL_STATE_TOKEN_KEY", self.ws)

	def test_no_query_spec_or_schema_changes_in_workspace_module(self):
		self.assertNotIn("QuerySpec", self.ws)
		self.assertNotIn("build_document_scope", self.ws)
		self.assertNotIn("apply_document_scope_filters", self.ws)


class TestAccountExplorerArchitectureFoundationWorkspace(unittest.TestCase):
	def test_architecture_still_includes_workspace_module(self):
		app_root = frappe.get_app_path("erpnext_extensions")
		path = os.path.join(
			app_root,
			"iran_accounting",
			"tests",
			"test_account_explorer_architecture_foundation.py",
		)
		with open(path, encoding="utf-8") as handle:
			content = handle.read()
		self.assertIn("explorer_workspace_state.js", content)
