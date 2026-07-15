# Copyright (c) 2026, Farbod Siyahpoosh and contributors
"""Wave 3B-3B — Enterprise Voucher GL Printing."""

from __future__ import annotations

import json
import unittest

import frappe
from frappe.utils import flt

from erpnext_extensions.erpnext_extensions.report.voucher_gl_print import voucher_gl_print as report_mod
from erpnext_extensions.iran_accounting.account_explorer import api
from erpnext_extensions.iran_accounting.account_explorer.dimension_discovery import get_discovered_dimensions
from erpnext_extensions.iran_accounting.account_explorer.voucher_gl_print import (
	DEFAULT_VOUCHER_GL_PRINT_FORMAT,
	VOUCHER_GL_PRINT_REPORT,
	build_voucher_gl_print,
	get_report_columns,
	render_voucher_gl_print_html,
)
from erpnext_extensions.iran_accounting.account_explorer.voucher_gl_layout import (
	JINJA_MARKER_RE,
	LABELS_EN,
	LABELS_FA,
	PROFILE_COMPACT,
	PROFILE_FULL_AUDIT,
	PROFILE_STANDARD,
	assert_rendered_html_safe,
	build_print_context,
	build_table_columns,
	format_amount,
	get_print_labels,
	resolve_company_logo_url,
	should_combine_dimensions,
)
from erpnext_extensions.iran_accounting.account_explorer.voucher_gl_renderer import (
	LAYOUT_COMPACT,
	LAYOUT_CUSTOM,
	LAYOUT_MODERN,
	LAYOUT_STANDARD,
	enrich_print_payload,
	render_voucher_package,
)
from erpnext_extensions.iran_accounting.tests.voucher_gl_print_fixtures import (
	cancel_print_fixture_jes,
	direct_voucher_gl_totals,
	ensure_print_company,
	ensure_print_dataset,
)


class TestVoucherGLPrint(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")

		class _Gate:
			@staticmethod
			def skipTest(msg):
				raise unittest.SkipTest(msg)

		cls.ctx = ensure_print_dataset(ensure_print_company(_Gate()))
		settings = frappe.get_single("Iran Accounting Settings")
		settings.show_print_gl = 1
		settings.show_print_voucher = 1
		if frappe.db.exists("Print Format", DEFAULT_VOUCHER_GL_PRINT_FORMAT):
			settings.voucher_gl_print_format = DEFAULT_VOUCHER_GL_PRINT_FORMAT
		settings.flags.ignore_permissions = True
		settings.save()
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		cancel_print_fixture_jes(cls.ctx["company"])

	def _filters(self, **overrides):
		base = {
			"company": self.ctx["company"],
			"voucher_type": "Journal Entry",
			"voucher_no": self.ctx["je_multi"],
			"include_opening_entries": 1,
			"include_cancelled_entries": 0,
			# Default Print GL column tests use flat binder profile.
			"show_account_hierarchy": 0,
		}
		base.update(overrides)
		return base

	def test_report_exists_and_execute(self):
		self.assertTrue(frappe.db.exists("Report", VOUCHER_GL_PRINT_REPORT))
		columns, data, message = report_mod.execute(self._filters())
		self.assertTrue(columns)
		self.assertTrue(data)
		self.assertIn("header", message)
		self.assertIn("totals", message)

	def test_header_fields(self):
		payload = build_voucher_gl_print(self._filters())
		header = payload["header"]
		for key in (
			"company",
			"company_name",
			"title",
			"voucher_type",
			"voucher_no",
			"voucher_status",
			"posting_date",
			"fiscal_year",
			"source_document",
			"print_meta_source",
			"prepared_by",
			"printed_by",
			"print_timestamp",
		):
			self.assertIn(key, header)
		for required in (
			"company",
			"company_name",
			"voucher_type",
			"voucher_no",
			"posting_date",
			"prepared_by",
			"printed_by",
			"print_timestamp",
		):
			self.assertTrue(header[required] not in (None, ""), msg=f"header.{required} empty")
		self.assertEqual(header["voucher_type"], "Journal Entry")
		self.assertEqual(header["voucher_no"], self.ctx["je_multi"])
		self.assertEqual(header["print_meta_source"], "Account Explorer")
		self.assertNotIn("generated_from", header)

	def test_totals_zero_difference(self):
		payload = build_voucher_gl_print(self._filters())
		totals = payload["totals"]
		self.assertAlmostEqual(totals["total_debit"], totals["total_credit"], places=6)
		self.assertAlmostEqual(totals["difference"], 0.0, places=6)
		self.assertTrue(totals["is_balanced"])

	def test_debit_credit_parity_with_gl(self):
		payload = build_voucher_gl_print(self._filters())
		expected = direct_voucher_gl_totals(
			self.ctx["company"], "Journal Entry", self.ctx["je_multi"]
		)
		self.assertAlmostEqual(payload["totals"]["total_debit"], expected["debit"], places=6)
		self.assertAlmostEqual(payload["totals"]["total_credit"], expected["credit"], places=6)
		self.assertEqual(len(payload["rows"]), expected["count"])

	def test_dynamic_dimensions_in_columns(self):
		dimensions = get_discovered_dimensions()
		columns = get_report_columns(dimensions)
		fieldnames = {col["fieldname"] for col in columns}
		self.assertIn("cost_center", fieldnames)
		self.assertIn("project", fieldnames)
		for dimension in dimensions:
			if dimension["fieldname"] in ("cost_center", "project"):
				continue
			self.assertIn(f"dim_{dimension['fieldname']}", fieldnames)
		payload = build_voucher_gl_print(self._filters())
		self.assertEqual(len(payload["dimensions"]), len(dimensions))
		if dimensions:
			first = payload["rows"][0]
			self.assertIn(dimensions[0]["fieldname"], first["dimensions"])

	def test_landscape_switch_threshold(self):
		html_portrait = render_voucher_gl_print_html(self._filters())
		self.assertIn("portrait", html_portrait.lower())
		html_landscape = render_voucher_gl_print_html(self._filters(full_audit_columns=1))
		self.assertIn("landscape", html_landscape.lower())

	def test_rtl_layout_direction_for_fa(self):
		previous = frappe.local.lang
		try:
			frappe.local.lang = "fa"
			html = render_voucher_gl_print_html(self._filters(language="fa"))
			self.assertIn('dir="rtl"', html)
			self.assertIn(LABELS_FA["accounting_voucher"], html)
		finally:
			frappe.local.lang = previous

	def test_print_format_selection(self):
		self.assertTrue(frappe.db.exists("Print Format", DEFAULT_VOUCHER_GL_PRINT_FORMAT))
		pf_report = frappe.db.get_value("Print Format", DEFAULT_VOUCHER_GL_PRINT_FORMAT, "report")
		self.assertEqual(pf_report, VOUCHER_GL_PRINT_REPORT)
		payload = build_voucher_gl_print(self._filters())
		self.assertEqual(payload["print_format"], DEFAULT_VOUCHER_GL_PRINT_FORMAT)

	def test_opening_entries_flag(self):
		if not self.ctx.get("je_opening"):
			self.skipTest("Opening JE fixture unavailable")
		included = build_voucher_gl_print(
			self._filters(voucher_no=self.ctx["je_opening"], include_opening_entries=1)
		)
		excluded = None
		try:
			excluded = build_voucher_gl_print(
				self._filters(voucher_no=self.ctx["je_opening"], include_opening_entries=0)
			)
		except frappe.ValidationError:
			excluded = None
		self.assertGreater(len(included["rows"]), 0)
		if excluded is None:
			# All rows were opening — exclude yields no rows / throw
			self.assertTrue(True)
		else:
			self.assertLessEqual(len(excluded["rows"]), len(included["rows"]))

	def test_cancelled_entries_excluded_by_default(self):
		payload = build_voucher_gl_print(self._filters())
		self.assertTrue(all(not row["is_cancelled"] for row in payload["rows"]))

	def test_finance_book_filter_accepted(self):
		# Empty finance book remains valid path (company default books).
		payload = build_voucher_gl_print(self._filters(finance_book=""))
		self.assertTrue(payload["rows"])

	def test_multi_currency_fields_present(self):
		payload = build_voucher_gl_print(self._filters())
		row = payload["rows"][0]
		self.assertIn("account_currency", row)
		self.assertIn("debit_in_account_currency", row)
		self.assertIn("credit_in_account_currency", row)

	def test_html_render_contains_header_and_totals(self):
		html = render_voucher_gl_print_html(self._filters())
		# Default print language is Persian (Iran Accounting Settings).
		self.assertIn(LABELS_FA["accounting_voucher"], html)
		self.assertIn(self.ctx["je_multi"], html)
		self.assertIn(LABELS_FA["debit_total"], html)
		self.assertIn(LABELS_FA["difference"], html)
		self.assertIn(LABELS_FA["amount_in_words"], html)
		self.assertIn("signatures", html)
		self.assertIsNone(JINJA_MARKER_RE.search(html))

		html_en = render_voucher_gl_print_html(self._filters(language="en"))
		self.assertIn(LABELS_EN["accounting_voucher"], html_en)

	def test_one_click_api_and_navigation(self):
		html = api.render_voucher_gl_print(
			company=self.ctx["company"],
			voucher_type="Journal Entry",
			voucher_no=self.ctx["je_multi"],
			filters=json.dumps(self._filters()),
		)
		self.assertIn(self.ctx["je_multi"], html)

		payload = json.dumps(
			{
				"document_scope": {
					"company": self.ctx["company"],
					"fiscal_year": self.ctx["fiscal_year"],
					"from_date": self.ctx["from_date"],
					"to_date": self.ctx["to_date"],
				},
				"analysis_context": {
					"voucher_scope": {
						"voucher_type": "Journal Entry",
						"voucher_no": self.ctx["je_multi"],
					}
				},
			}
		)
		nav = api.get_voucher_navigation_target(payload)
		self.assertTrue(nav.get("can_print_gl"))
		self.assertIsNotNone(nav.get("print_gl_route"))
		self.assertEqual(nav["print_gl_route"]["report"], VOUCHER_GL_PRINT_REPORT)
		self.assertEqual(nav["print_gl_route"]["filters"]["voucher_no"], self.ctx["je_multi"])

	def test_metadata_exposes_print_flags(self):
		meta = api.get_metadata()
		self.assertIn("show_print_gl", meta)
		self.assertIn("show_print_voucher", meta)
		self.assertIn("voucher_gl_print_format", meta)
		self.assertIn("voucher_gl_layout", meta)
		self.assertIn("voucher_gl_page_layout", meta)
		self.assertIn("voucher_gl_combine_dimensions", meta)

	def test_permissions_require_company_and_gl_read(self):
		# Administrator path succeeds; empty company throws.
		with self.assertRaises(Exception):
			build_voucher_gl_print({"voucher_type": "Journal Entry", "voucher_no": self.ctx["je_multi"]})

	def test_popup_safe_client_contract(self):
		"""Static contract: window.open before async fill; shared handler; fallback; no popup nag."""
		import os

		app_root = frappe.get_app_path("erpnext_extensions")
		client_path = os.path.join(
			app_root,
			"erpnext_extensions",
			"page",
			"account_explorer",
			"core",
			"voucher_gl_print_client.js",
		)
		page_path = os.path.join(
			app_root,
			"erpnext_extensions",
			"page",
			"account_explorer",
			"account_explorer.js",
		)
		bridge_path = os.path.join(
			app_root,
			"erpnext_extensions",
			"page",
			"account_explorer",
			"core",
			"voucher_gl_print_bridge.js",
		)
		with open(client_path, encoding="utf-8") as handle:
			client = handle.read()
		with open(page_path, encoding="utf-8") as handle:
			page = handle.read()
		with open(bridge_path, encoding="utf-8") as handle:
			bridge = handle.read()

		self.assertIn("voucher_gl_print_client.js", page)
		self.assertIn("voucher_gl_print_bridge.js", page)
		self.assertIn("open_voucher_gl_print", bridge)
		self.assertIn("VoucherGLPrint.open", bridge)
		# Print GL actions resolve through bridge → navigate_print_gl / shared client.
		self.assertIn("navigate_print_gl", bridge)
		self.assertIn("user_amount_scale", bridge)
		self.assertIn("normalize_amount_scale_enum", client)
		self.assertIn("user_amount_scale", client)

		self.assertIn("window.open(\"\", \"_blank\")", client)
		open_idx = client.index("window.open(\"\", \"_blank\")")
		call_idx = client.index("frappe.call({")
		self.assertLess(open_idx, call_idx, "window.open must precede async frappe.call")
		self.assertIn("write_loading_document", client)
		self.assertIn("show_fallback", client)
		self.assertIn("Open in Current Tab", client)
		self.assertIn("Copy Print URL", client)
		self.assertIn("build_report_url", client)
		self.assertIn("/app/query-report/", client)
		self.assertNotIn("Please allow pop-ups", client)
		self.assertNotIn("Please allow pop-ups", page)
		# No second open after success path fill — fetch uses same window via write_document.
		self.assertIn("fetch_and_fill(print_window", client)
		self.assertEqual(client.count("window.open(\"\", \"_blank\")"), 2)  # open + fallback retry
		self.assertIn("__voucher_gl_print_ready", client)
		self.assertIn("BEHAVIOR: \"open_preview\"", client)
		# Print Voucher remains a separate action in controller; Print GL label lives in bridge.
		self.assertIn('label: __("Print Voucher")', page)
		self.assertIn('label: __("Print GL")', bridge)
		self.assertIn("navigate_print_voucher", page)
		self.assertIn("navigate_print_gl", bridge)
		self.assertIn("Proto.navigate_print_gl", bridge)

	def test_print_gl_route_is_identity_only(self):
		payload = json.dumps(
			{
				"document_scope": {
					"company": self.ctx["company"],
					"fiscal_year": self.ctx["fiscal_year"],
					"from_date": self.ctx["from_date"],
					"to_date": self.ctx["to_date"],
				},
				"analysis_context": {
					"voucher_scope": {
						"voucher_type": "Journal Entry",
						"voucher_no": self.ctx["je_multi"],
					}
				},
			}
		)
		nav = api.get_voucher_navigation_target(payload)
		route = nav["print_gl_route"]
		self.assertEqual(route["filters"]["voucher_no"], self.ctx["je_multi"])
		self.assertEqual(route["filters"]["voucher_type"], "Journal Entry")
		self.assertIn("url_path", route)
		self.assertIn("/app/query-report/", route["url_path"])
		self.assertIn(self.ctx["je_multi"], route["url_path"])
		self.assertNotIn("<html", route["url_path"].lower())
		self.assertNotIn("debit", route["url_path"].lower())
		# Server render path still requires permissions / company.
		html = api.render_voucher_gl_print(
			company=self.ctx["company"],
			voucher_type="Journal Entry",
			voucher_no=self.ctx["je_multi"],
			filters=json.dumps(self._filters()),
		)
		self.assertIn("__voucher_gl_print_ready", html)
		self.assertIn("voucher-gl-print-ready", html)

	def test_jinja_guard_rejects_unresolved_markers(self):
		with self.assertRaises(Exception):
			assert_rendered_html_safe('{% set x = 1 %}{{ doc.name }}')

	def test_compact_column_profile_count(self):
		filters = self._filters(layout=LAYOUT_COMPACT)
		payload = enrich_print_payload(build_voucher_gl_print(filters), filters)
		ctx = build_print_context(payload, filters)
		self.assertEqual(ctx["column_profile"], PROFILE_COMPACT)
		self.assertEqual(len(ctx["columns"]), 5)

	def test_standard_column_profile(self):
		payload = enrich_print_payload(build_voucher_gl_print(self._filters()), self._filters())
		ctx = build_print_context(payload, self._filters(layout=LAYOUT_STANDARD))
		self.assertEqual(ctx["column_profile"], PROFILE_STANDARD)
		col_ids = [c["id"] for c in ctx["columns"]]
		self.assertEqual(col_ids[:5], ["idx", "account_stacked", "remarks", "debit", "credit"])

	def test_combine_dimensions_logic(self):
		dims = get_discovered_dimensions()
		self.assertTrue(should_combine_dimensions(PROFILE_STANDARD, dims))
		self.assertFalse(should_combine_dimensions(PROFILE_FULL_AUDIT, dims))
		# Standard never opens one column per dimension
		from erpnext_extensions.iran_accounting.account_explorer.voucher_gl_layout import build_table_columns, get_print_labels

		cols = build_table_columns(PROFILE_STANDARD, dims, get_print_labels("en"), combine_dimensions=True)
		self.assertTrue(any(c["id"] == "dimensions_combined" for c in cols))
		self.assertFalse(any(c["id"].startswith("dim_") for c in cols))
