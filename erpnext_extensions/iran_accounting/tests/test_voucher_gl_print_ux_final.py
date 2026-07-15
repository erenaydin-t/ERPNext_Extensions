# Copyright (c) 2026, Farbod Siyahpoosh and contributors
"""Wave 3B-3B.5 — Persian voucher print UX finalization tests."""

from __future__ import annotations

import os
import re
import time
import tracemalloc
import unittest

import frappe
from frappe.utils import flt

from erpnext_extensions.iran_accounting.account_explorer.voucher_gl_layout import (
	LABELS_EN,
	LABELS_FA,
	build_hierarchy_code_html,
	build_hierarchy_description_html,
	localize_currency_label,
)
from erpnext_extensions.iran_accounting.account_explorer.voucher_gl_print import build_voucher_gl_print
from erpnext_extensions.iran_accounting.account_explorer.voucher_gl_renderer import (
	enrich_print_payload,
	render_voucher_package,
	resolve_amount_in_words,
)
from erpnext_extensions.iran_accounting.tests.voucher_gl_print_fixtures import (
	ensure_hierarchy_business_fixture,
	ensure_print_company,
)


EN_REPORT_BARS = (
	"VOUCHER INFORMATION",
	"ACCOUNTING ENTRIES",
	"Accounting Entries",
	"Voucher Information",
)


class TestVoucherGLPrintUXFinal(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")

		class _Gate:
			@staticmethod
			def skipTest(msg):
				raise unittest.SkipTest(msg)

		cls.ctx = ensure_hierarchy_business_fixture(ensure_print_company(_Gate()))
		settings = frappe.get_single("Iran Accounting Settings")
		settings.voucher_gl_show_account_hierarchy = 1
		settings.voucher_gl_hierarchy_start_level = 2
		settings.voucher_gl_show_party_breakdown = 1
		settings.voucher_gl_show_dimension_breakdown = 1
		settings.voucher_gl_show_group_subtotals = 1
		settings.flags.ignore_permissions = True
		settings.save()
		frappe.db.commit()

	def _filters(self, **extra):
		base = {
			"company": self.ctx["company"],
			"voucher_type": "Journal Entry",
			"voucher_no": self.ctx["hier_je"],
			"layout": "Standard",
			"show_account_hierarchy": 1,
			"user_amount_scale": "Raw",
			"include_opening_entries": 1,
		}
		base.update(extra)
		return base

	def test_fa_labels_only_in_fa_mode(self):
		html = render_voucher_package(self._filters(language="fa"))
		self.assertIn('lang="fa"', html)
		self.assertIn('dir="rtl"', html)
		for key in (
			"accounting_voucher",
			"voucher_number",
			"posting_date",
			"line_amount",
			"debit",
			"credit",
			"amount_in_words",
			"section_entries",
			"print_origin_explorer",
		):
			self.assertIn(LABELS_FA[key], html)
		self.assertNotIn("Accounting Voucher", html)
		self.assertNotIn("Line Amount", html)
		self.assertNotIn("Generated From: Account Explorer", html)
		self.assertIn(f"{LABELS_FA['generated_from']}", html)
		self.assertIn(LABELS_FA["print_origin_explorer"], html)

	def test_en_labels_only_in_en_mode(self):
		html = render_voucher_package(self._filters(language="en"))
		self.assertIn('lang="en"', html)
		self.assertIn(LABELS_EN["accounting_voucher"], html)
		self.assertIn(LABELS_EN["line_amount"], html)
		self.assertNotIn(LABELS_FA["accounting_voucher"], html)

	def test_no_english_report_bars_in_fa(self):
		html = render_voucher_package(self._filters(language="fa"))
		for bar in EN_REPORT_BARS:
			self.assertNotIn(bar, html)
		self.assertIn(LABELS_FA["section_entries"], html)
		# Uppercase report bars are scoped to English only
		self.assertIn('html[lang="en"] .section-label', html)

	def test_hierarchy_1201_to_120123(self):
		payload = enrich_print_payload(build_voucher_gl_print(self._filters()), self._filters())
		html = render_voucher_package(self._filters(language="fa"))
		leaf_rows = [r for r in payload["rows"] if r.get("account") == self.ctx["hier_leaf"]]
		hier = leaf_rows[0]["account_hierarchy"]
		nums = [n["account_number"] for n in hier]
		self.assertLess(nums.index("1201"), nums.index("120123"))
		self.assertIn("1201", nums)
		self.assertIn("120123", nums)
		self.assertIn("موجودی مواد و کالا", html)
		self.assertIn("کنترل خرید داخلی", html)
		self.assertIn("hier-code", html)
		# Codes paired in code column for the account header group
		account_headers = [n for n in payload["display_nodes"] if n.get("node_type") == "account_header"]
		leaf_header = next(n for n in account_headers if n.get("account") == self.ctx["hier_leaf"])
		code_html = build_hierarchy_code_html(leaf_header.get("account_hierarchy"))
		self.assertIn("1201", code_html)
		self.assertIn("120123", code_html)
		title_html = build_hierarchy_description_html(leaf_header, LABELS_FA, rtl=True)
		self.assertIn("موجودی مواد و کالا", title_html)
		self.assertNotIn('acct-code', title_html)  # titles only in شرح for headers

	def test_party_and_dimension_groups(self):
		payload = enrich_print_payload(build_voucher_gl_print(self._filters()), self._filters())
		nodes = payload["display_nodes"]
		self.assertGreaterEqual(len([n for n in nodes if n["node_type"] == "party_header"]), 2)
		html = render_voucher_package(self._filters(language="fa"))
		self.assertIn("تأمین‌کننده", html)
		# Dimension values / labels present without empty technical English labels
		self.assertNotIn("Party Type:", html)
		self.assertNotIn("Description:", html)
		self.assertNotIn("Facility:", html)

	def test_row_remarks_and_subtotals(self):
		payload = enrich_print_payload(build_voucher_gl_print(self._filters()), self._filters())
		leaf_lines = [
			n
			for n in payload["display_nodes"]
			if n.get("node_type") == "gl_line" and n.get("account") == self.ctx["hier_leaf"]
		]
		remarks = " ".join((n.get("description") or {}).get("main") or "" for n in leaf_lines)
		self.assertTrue("الف" in remarks or "ب" in remarks)
		leaf_rows = [r for r in payload["rows"] if r.get("account") == self.ctx["hier_leaf"]]
		leaf_debit = sum(flt(r.get("debit")) for r in leaf_rows)
		for sub in payload["display_nodes"]:
			if sub.get("node_type") == "account_subtotal" and sub.get("account") == self.ctx["hier_leaf"]:
				self.assertAlmostEqual(flt(sub.get("debit")), leaf_debit, places=6)
		self.assertEqual(flt(payload["totals"]["difference"], 9), 0)

	def test_amount_scales_fa_no_kmbt(self):
		for scale in ("Raw", "Thousands", "Millions"):
			html = render_voucher_package(
				self._filters(language="fa", user_amount_scale=scale, amount_scale=scale)
			)
			self.assertNotRegex(html, r"\b[KMBT]\b")
			if scale == "Millions":
				self.assertIn("میلیون", html)
			if scale == "Thousands":
				self.assertIn("هزار", html)

	def test_amount_in_words_fa_not_english(self):
		words = resolve_amount_in_words(12_000_000, "IRR", "fa")
		if words:
			self.assertFalse(re.search(r"\b(Twelve|Million|Only)\b", words, re.I))
			self.assertIn("ریال", words)
		payload = enrich_print_payload(
			build_voucher_gl_print(self._filters(language="fa")), self._filters(language="fa")
		)
		aiw = payload["totals"].get("amount_in_words") or ""
		if aiw:
			self.assertFalse(re.search(r"\b(Twelve|Million|Only)\b", aiw, re.I))

	def test_currency_label_and_no_broken_glyph(self):
		self.assertEqual(localize_currency_label("IRR", "fa"), "ریال")
		self.assertEqual(localize_currency_label("USD", "fa"), "USD")
		html = render_voucher_package(self._filters(language="fa"))
		self.assertNotIn("﷼", html)
		self.assertNotIn("�", html)

	def test_no_jinja_escape_and_empty_labels(self):
		html = render_voucher_package(self._filters(language="fa"))
		self.assertNotRegex(html, r"(\{%|\{\{)")
		self.assertNotIn(": </span></div>", html.replace(" ", ""))

	def test_settings_fa_csv_translations(self):
		path = frappe.get_app_path("erpnext_extensions", "translations", "fa.csv")
		self.assertTrue(os.path.isfile(path))
		text = open(path, encoding="utf-8").read()
		required = [
			"Voucher Printing,چاپ سند",
			"Show Print GL,نمایش چاپ سند حسابداری",
			"Voucher GL Printing,چاپ سند حسابداری",
			"Show Account Hierarchy,نمایش سلسله‌مراتب حساب",
			"Hierarchy Start Level,شروع نمایش از سطح حساب",
			"Show Party Breakdown,تفکیک طرف حساب",
			"Show Dimension Breakdown,تفکیک ابعاد تحلیلی",
			"Show Group Subtotals,نمایش جمع گروه‌ها",
			"Amount Scale,مقیاس نمایش مبلغ",
		]
		for line in required:
			self.assertIn(line, text)

	def test_render_perf_batch_sizes(self):
		"""Batch hierarchy must stay practical through 1000 synthetic display nodes."""
		# Use real voucher enrichment as baseline; stress grouping with cloned rows.
		base = enrich_print_payload(build_voucher_gl_print(self._filters()), self._filters())
		rows = base["rows"]
		results = {}
		from erpnext_extensions.iran_accounting.account_explorer.voucher_gl_hierarchy import (
			group_print_rows,
		)

		for n in (10, 100, 500, 1000):
			synthetic = []
			while len(synthetic) < n:
				synthetic.extend(rows)
			synthetic = synthetic[:n]
			tracemalloc.start()
			t0 = time.perf_counter()
			nodes = group_print_rows(synthetic, show_party=True, show_dimensions=True, show_subtotals=True)
			elapsed = time.perf_counter() - t0
			_current, peak = tracemalloc.get_traced_memory()
			tracemalloc.stop()
			results[n] = {"seconds": round(elapsed, 4), "peak_mb": round(peak / (1024 * 1024), 3), "nodes": len(nodes)}
			self.assertGreater(len(nodes), 0)
			self.assertLess(elapsed, 5.0, msg=f"{n} rows took {elapsed}s")
		import json

		out_dir = frappe.get_app_path("erpnext_extensions", ".local_artifacts")
		os.makedirs(out_dir, exist_ok=True)
		report = os.path.join(out_dir, "voucher_gl_ux_perf.json")
		with open(report, "w", encoding="utf-8") as fh:
			json.dump(results, fh, indent=2)
		self._perf_results = results


if __name__ == "__main__":
	unittest.main()
