# Copyright (c) 2026, Farbod Siyahpoosh and contributors
"""Wave 3B-3B.1 — Enterprise Voucher GL Cover & Printing."""

from __future__ import annotations

import json
import unittest

import frappe

from erpnext_extensions.iran_accounting.account_explorer import api
from erpnext_extensions.iran_accounting.account_explorer.dimension_discovery import get_discovered_dimensions
from erpnext_extensions.iran_accounting.account_explorer.voucher_gl_print import (
	DEFAULT_VOUCHER_GL_PRINT_FORMAT,
	build_voucher_gl_print,
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
	LAYOUT_AUDIT,
	LAYOUT_COMPACT,
	LAYOUT_CUSTOM,
	LAYOUT_MODERN,
	LAYOUT_STANDARD,
	collect_source_attachments,
	enrich_print_payload,
	render_voucher_package,
	resolve_voucher_gl_layout,
)
from erpnext_extensions.iran_accounting.tests.voucher_gl_print_fixtures import (
	cancel_print_fixture_jes,
	ensure_print_company,
	ensure_print_dataset,
)


class TestVoucherGLCover(unittest.TestCase):
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
		settings.voucher_gl_layout = LAYOUT_STANDARD
		settings.append_source_attachments = 0
		for field, value in (
			("voucher_gl_show_logo", 1),
			("voucher_gl_show_letterhead", 0),
			("voucher_gl_show_amount_in_words", 1),
			("voucher_gl_show_signature_block", 1),
			("voucher_gl_hide_empty_columns", 1),
			("voucher_gl_auto_orientation", 1),
			("voucher_gl_combine_dimensions", 1),
			("voucher_gl_page_layout", "Auto"),
		):
			if settings.meta.has_field(field):
				settings.set(field, value)
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
			"layout": LAYOUT_STANDARD,
			# Cover suite targets flat binder columns; hierarchy covered elsewhere.
			"show_account_hierarchy": 0,
			# English assertions (print_meta_source, section bars) — independent of site FA default.
			"language": "en",
		}
		base.update(overrides)
		return base

	def test_header_extended_fields(self):
		payload = build_voucher_gl_print(self._filters())
		header = payload["header"]
		for key in (
			"voucher_status",
			"voucher_remarks",
			"reference_number",
			"prepared_by",
			"printed_by",
			"print_timestamp",
			"fiscal_year",
			"source_document",
			"print_meta_source",
		):
			self.assertIn(key, header)
		self.assertNotIn("generated_from", header)

	def test_voucher_summary_block(self):
		payload = enrich_print_payload(build_voucher_gl_print(self._filters()), self._filters())
		summary = payload["summary"]
		self.assertGreater(summary["gl_row_count"], 0)
		self.assertIn("balanced_label", summary)
		self.assertTrue(summary["is_balanced"])
		self.assertIn("✔", summary["balanced_label"])
		self.assertEqual(summary["print_meta_source"], "Account Explorer")
		self.assertNotIn("generated_from", summary)

	def test_totals_amount_in_words(self):
		payload = enrich_print_payload(build_voucher_gl_print(self._filters()), self._filters())
		self.assertTrue(payload["totals"].get("amount_in_words"))

	def test_difference_highlight_when_unbalanced_payload(self):
		payload = enrich_print_payload(build_voucher_gl_print(self._filters()), self._filters())
		payload["totals"]["difference"] = 1.0
		payload["totals"]["is_balanced"] = False
		payload["summary"]["is_balanced"] = False
		payload["summary"]["balanced_label"] = "✖ Difference"
		self.assertIn("✖", payload["summary"]["balanced_label"])

	def test_signature_section_in_html(self):
		html = render_voucher_package(self._filters())
		for label in (
			"Prepared By",
			"Reviewed By",
			"Financial Manager",
			"Chief Accountant",
		):
			self.assertIn(label, html)
		self.assertIn('data-section="signatures"', html)
		html_fa = render_voucher_package(self._filters(language="fa"))
		for label in (
			LABELS_FA["prepared_by"],
			LABELS_FA["checked_by"],
			LABELS_FA["financial_manager"],
			LABELS_FA["accounting_manager"],
		):
			self.assertIn(label, html_fa)

	def test_portrait_and_landscape(self):
		html_p = render_voucher_package(self._filters())
		self.assertIn("portrait", html_p.lower())
		html_l = render_voucher_package(self._filters(layout=LAYOUT_AUDIT))
		self.assertIn("landscape", html_l.lower())

	def test_audit_layout_profile(self):
		html = render_voucher_package(self._filters(layout=LAYOUT_AUDIT))
		self.assertIn("vgl-layout-audit", html)
		self.assertIn("landscape", html.lower())
		ctx = build_print_context(
			enrich_print_payload(build_voucher_gl_print(self._filters()), self._filters(layout=LAYOUT_AUDIT)),
			self._filters(layout=LAYOUT_AUDIT),
		)
		self.assertEqual(ctx["column_profile"], PROFILE_FULL_AUDIT)
		self.assertFalse(ctx["combine_dimensions"])
		self.assertEqual(ctx["orientation"], "Landscape")

	def test_repeated_page_header_banner(self):
		html = render_voucher_package(self._filters())
		self.assertIn("repeat-banner", html)
		self.assertIn(self.ctx["je_multi"], html)

	def test_dynamic_dimensions_still_present(self):
		dims = get_discovered_dimensions()
		html = render_voucher_package(self._filters())
		# Combined dimensions mode — labels appear in cell content or column header.
		if len(dims) > 2:
			self.assertIn(LABELS_EN["analytical_dimensions"], html)
		else:
			for dim in dims:
				self.assertIn(dim["label"], html)

	def test_rtl_and_ltr(self):
		prev = frappe.local.lang
		try:
			frappe.local.lang = "fa"
			html_rtl = render_voucher_package(self._filters(language="fa"))
			self.assertIn('dir="rtl"', html_rtl)
			self.assertIn(LABELS_FA["accounting_voucher"], html_rtl)
			self.assertIn(LABELS_FA["print"], html_rtl)
			frappe.local.lang = "en"
			html_ltr = render_voucher_package(self._filters(language="en"))
			self.assertIn('dir="ltr"', html_ltr)
			self.assertIn(LABELS_EN["accounting_voucher"], html_ltr)
		finally:
			frappe.local.lang = prev

	def test_standard_modern_compact_layouts(self):
		for layout in (LAYOUT_STANDARD, LAYOUT_MODERN, LAYOUT_COMPACT):
			html = render_voucher_package(self._filters(layout=layout))
			self.assertIn(f"vgl-layout-{layout.lower().replace(' ', '-')}", html)
			self.assertIn('data-section="voucher-summary"', html)
			self.assertIn('data-section="gl-table"', html)
			self.assertIn(LABELS_EN["account_combined"], html)
		compact_html = render_voucher_package(self._filters(layout=LAYOUT_COMPACT))
		self.assertIn(LABELS_EN["account_combined"], compact_html)

	def test_custom_print_format_layout(self):
		html = render_voucher_package(self._filters(layout=LAYOUT_CUSTOM))
		self.assertIn("vgl-layout-custom", html)
		self.assertIn("Accounting Voucher", html)

	def test_layout_setting_resolution(self):
		settings = frappe.get_single("Iran Accounting Settings")
		settings.voucher_gl_layout = LAYOUT_MODERN
		settings.flags.ignore_permissions = True
		settings.save()
		frappe.db.commit()
		self.assertEqual(resolve_voucher_gl_layout({}), LAYOUT_MODERN)
		self.assertEqual(resolve_voucher_gl_layout({"layout": LAYOUT_COMPACT}), LAYOUT_COMPACT)
		settings.voucher_gl_layout = LAYOUT_STANDARD
		settings.flags.ignore_permissions = True
		settings.save()
		frappe.db.commit()

	def test_attachment_append_empty_by_default(self):
		payload = enrich_print_payload(
			build_voucher_gl_print(self._filters()),
			self._filters(append_source_attachments=1),
		)
		self.assertEqual(payload["attachments"], collect_source_attachments("Journal Entry", self.ctx["je_multi"]))
		html = render_voucher_package(self._filters(append_source_attachments=1))
		# No files → no attachment sections
		self.assertNotIn('data-section="attachment"', html)

	def test_attachment_append_when_file_present(self):
		# Attach a tiny text renamed as png wouldn't work; create File stub with image name.
		file_doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": "vgl-test-attachment.png",
				"is_private": 0,
				"content": "iVBORw0KGgo=",
				"decode": True,
				"attached_to_doctype": "Journal Entry",
				"attached_to_name": self.ctx["je_multi"],
			}
		)
		file_doc.flags.ignore_permissions = True
		try:
			file_doc.insert()
			frappe.db.commit()
			html = render_voucher_package(self._filters(append_source_attachments=1))
			self.assertIn('data-section="attachment"', html)
			self.assertIn("vgl-test-attachment.png", html)
		finally:
			if frappe.db.exists("File", file_doc.name):
				frappe.delete_doc("File", file_doc.name, force=1)
				frappe.db.commit()

	def test_opening_voucher_html(self):
		if not self.ctx.get("je_opening"):
			self.skipTest("Opening JE unavailable")
		html = render_voucher_package(
			self._filters(voucher_no=self.ctx["je_opening"], include_opening_entries=1)
		)
		self.assertIn("Opening", html)

	def test_cancelled_flag_in_summary(self):
		payload = enrich_print_payload(build_voucher_gl_print(self._filters()), self._filters())
		self.assertFalse(payload["summary"]["cancelled"])

	def test_multi_currency_columns_in_html(self):
		html = render_voucher_package(self._filters(full_audit_columns=1))
		self.assertIn("Debit (AC)", html)
		self.assertIn("Account Currency", html)

	def test_one_click_api_uses_cover_renderer(self):
		html = api.render_voucher_gl_print(
			company=self.ctx["company"],
			voucher_type="Journal Entry",
			voucher_no=self.ctx["je_multi"],
			filters=json.dumps(self._filters()),
		)
		self.assertIn("voucher-summary", html)
		self.assertIn("signatures", html)
		self.assertIn("Amount in Words", html)

	def test_metadata_exposes_layout(self):
		meta = api.get_metadata()
		self.assertIn("voucher_gl_layout", meta)
		self.assertIn("append_source_attachments", meta)

	def test_no_raw_jinja_in_final_html(self):
		html = render_voucher_package(self._filters())
		self.assertIsNone(JINJA_MARKER_RE.search(html))
		assert_rendered_html_safe(html)

	def test_html_escaping_in_remarks(self):
		payload = enrich_print_payload(build_voucher_gl_print(self._filters()), self._filters())
		payload["rows"][0]["remarks"] = '<script>alert("x")</script>'
		from erpnext_extensions.iran_accounting.account_explorer.voucher_gl_renderer import _render_builtin

		html = _render_builtin(payload, self._filters())
		self.assertIn("&lt;script&gt;alert", html)
		self.assertNotIn('<div class="remarks-main"><script>', html)

	def test_combined_dimensions_when_many(self):
		dims = get_discovered_dimensions()
		payload = enrich_print_payload(build_voucher_gl_print(self._filters()), self._filters())
		ctx = build_print_context(payload, self._filters())
		if len(dims) > 2:
			self.assertTrue(ctx["combine_dimensions"])
			col_ids = {c["id"] for c in ctx["columns"]}
			self.assertIn("dimensions_combined", col_ids)
			self.assertNotIn("dim_ee_gl_prec_test_dim", col_ids)

	def test_full_audit_profile_columns(self):
		payload = enrich_print_payload(build_voucher_gl_print(self._filters()), self._filters())
		ctx_full = build_print_context(
			payload, self._filters(full_audit_columns=1, hide_empty_columns=0)
		)
		self.assertEqual(ctx_full["column_profile"], PROFILE_FULL_AUDIT)
		col_ids = {c["id"] for c in ctx_full["columns"]}
		self.assertIn("account_currency", col_ids)
		self.assertIn("detail_ref", col_ids)
		# Empty optional columns stay hidden when Hide Empty Columns is on (Audit included).
		ctx_hide = build_print_context(
			payload, self._filters(full_audit_columns=1, hide_empty_columns=1)
		)
		hide_ids = {c["id"] for c in ctx_hide["columns"]}
		self.assertIn("account_currency", hide_ids)
		self.assertNotIn("detail_ref", hide_ids)

	def test_logo_url_or_omitted(self):
		url = resolve_company_logo_url(self.ctx["company"])
		html = render_voucher_package(self._filters())
		if url:
			self.assertIn(url, html)
		else:
			self.assertNotIn('class="company-logo"', html)

	def test_no_generated_from_in_header_html(self):
		"""Cover secondary meta may show Generated From / محل چاپ; not a source-doc identity field."""
		html = render_voucher_package(self._filters())
		self.assertIn("Generated From", html)
		self.assertIn("Account Explorer", html)
		self.assertIn("Printed from ERPNext Iran Accounting", html)
		payload = enrich_print_payload(build_voucher_gl_print(self._filters()), self._filters())
		self.assertNotIn("generated_from", payload["header"])
		self.assertEqual(payload["summary"]["print_meta_source"], "Account Explorer")

	def test_continuation_not_in_first_page_table_banner(self):
		"""Continued / ادامه سند must not appear in thead repeat banner (page-1 leak)."""
		html_en = render_voucher_package(self._filters())
		html_fa = render_voucher_package(self._filters(language="fa"))
		# Extract thead banner cell only
		import re

		for html, continued in ((html_en, "Continued"), (html_fa, "ادامه سند")):
			m = re.search(r'class="repeat-banner"[^>]*>.*?</tr>', html, re.S)
			self.assertTrue(m)
			self.assertNotIn(continued, m.group(0))
		# Page 2+ continuation is reserved for @page top (not first)
		self.assertIn("@page :first", html_fa)
		self.assertIn(LABELS_FA["continuing_header"], html_fa)

	def test_amount_format_no_abbreviation(self):
		formatted = format_amount(1_700_000, "INR", 2)
		for token in ("K", "M", "B", "T"):
			self.assertNotIn(f" {token}", formatted)
		self.assertIn("1,700,000", formatted.replace(" ", ""))

	def test_irr_integer_formatting(self):
		formatted = format_amount(650, "IRR", 0)
		self.assertNotIn(".00", formatted)

	def test_unbalanced_highlight(self):
		payload = enrich_print_payload(build_voucher_gl_print(self._filters()), self._filters())
		payload["totals"]["difference"] = 10
		payload["totals"]["is_balanced"] = False
		payload["summary"]["is_balanced"] = False
		from erpnext_extensions.iran_accounting.account_explorer.voucher_gl_renderer import _render_builtin

		html = _render_builtin(payload, self._filters())
		self.assertIn("diff-alert", html)
		self.assertIn(LABELS_EN["balanced_bad"], html)

	def test_first_page_cover_and_repeat_header_css(self):
		html = render_voucher_package(self._filters())
		self.assertIn('data-section="cover"', html)
		self.assertIn("repeat-banner", html)
		self.assertIn("table-header-group", html)

	def test_long_persian_remarks_wrap_markup(self):
		payload = enrich_print_payload(build_voucher_gl_print(self._filters()), self._filters(language="fa"))
		payload["rows"][0]["remarks"] = "شرح طولانی " * 40
		from erpnext_extensions.iran_accounting.account_explorer.voucher_gl_renderer import _render_builtin

		html = _render_builtin(payload, self._filters(language="fa"))
		self.assertIn("remarks-main", html)
		self.assertIn("unicode-bidi: plaintext", html)
