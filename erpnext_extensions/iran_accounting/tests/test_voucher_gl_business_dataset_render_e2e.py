# Copyright (c) 2026, Farbod Siyahpoosh and contributors
"""API E2E: render_voucher_gl_print against AET realistic vouchers."""

from __future__ import annotations

import re
import time
import tracemalloc
import unittest

import frappe
from frappe.utils import flt

from erpnext_extensions.iran_accounting.account_explorer import api
from erpnext_extensions.iran_accounting.tests.voucher_gl_business_dataset import (
	EXPECTED_PRINT_HIERARCHY,
	POSTING_ACCOUNT,
	ensure_voucher_gl_business_dataset,
)


class TestVoucherGLBusinessDatasetRenderE2E(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")
		cls.ds = ensure_voucher_gl_business_dataset()
		settings = frappe.get_single("Iran Accounting Settings")
		settings.voucher_gl_print_language = "Persian"
		settings.voucher_gl_show_account_hierarchy = 1
		settings.voucher_gl_hierarchy_start_level = 2
		settings.voucher_gl_amount_scale = "Raw"
		settings.flags.ignore_permissions = True
		settings.save()
		frappe.db.commit()

	def _filters(self, voucher_no: str, **extra):
		base = {
			"company": self.ds["company"],
			"voucher_type": "Journal Entry",
			"voucher_no": voucher_no,
			"layout": "Standard",
			"show_account_hierarchy": 1,
			"account_hierarchy_start_level": 2,
			"user_amount_scale": "Raw",
			"amount_scale": "Raw",
			"include_opening_entries": 1,
		}
		base.update(extra)
		return base

	def _render(self, voucher_no: str, **extra) -> str:
		filters = self._filters(voucher_no, **extra)
		frappe.local.lang = "en"
		return api.render_voucher_gl_print(
			company=filters["company"],
			voucher_type=filters["voucher_type"],
			voucher_no=filters["voucher_no"],
			filters=filters,
		)

	def test_basic_hierarchy_html(self):
		v1 = next(v for v in self.ds["vouchers"] if v["key"] == "v1_basic")
		html = self._render(v1["name"])
		self.assertIn('dir="rtl"', html)
		self.assertIn("سند حسابداری", html)
		self.assertIn('class="account-hierarchy"', html)
		for code, title in EXPECTED_PRINT_HIERARCHY:
			self.assertIn(code, html)
			self.assertIn(title, html)
		self.assertNotRegex(html, r'account-hierarchy"[^>]*>\s*<div class="hier-pair"[^>]*>\s*<span class="acct-code">1110040101</span>\s*</div>\s*</div>')
		# Level-1 omitted
		codes = re.findall(r'class="acct-code"[^>]*>([^<]+)', html)
		bank_chain = [c for c in codes if c.startswith("111")]
		self.assertIn("1110", bank_chain)
		self.assertIn(POSTING_ACCOUNT, bank_chain)
		self.assertNotIn("11", bank_chain)
		self.assertNotIn("{{", html)
		self.assertNotRegex(html, r"\b[KMBT]\b")
		self.assertIn("hier-code", html)
		self.assertIn("hier-title", html)

	def test_multi_line_and_suppliers(self):
		v2 = next(v for v in self.ds["vouchers"] if v["key"] == "v2_multi_line")
		html = self._render(v2["name"])
		self.assertIn("واریز قسط ۱", html)
		self.assertIn("واریز قسط ۲", html)
		self.assertIn("واریز قسط ۳", html)
		self.assertGreaterEqual(html.count('class="account-hierarchy"'), 2)

		v4 = next(v for v in self.ds["vouchers"] if v["key"] == "v4_suppliers")
		html4 = self._render(v4["name"])
		self.assertIn("AET Supplier A", html4)
		self.assertIn("AET Supplier B", html4)
		self.assertTrue("تأمین" in html4 or "Supplier" in html4)
	def test_combined_complexity_and_performance(self):
		v8 = next(v for v in self.ds["vouchers"] if v["key"] == "v8_combined")
		gl_count = frappe.db.count(
			"GL Entry",
			{"voucher_type": "Journal Entry", "voucher_no": v8["name"], "is_cancelled": 0},
		)
		tracemalloc.start()
		t0 = time.perf_counter()
		html = self._render(v8["name"])
		elapsed_ms = (time.perf_counter() - t0) * 1000
		_current, peak = tracemalloc.get_traced_memory()
		tracemalloc.stop()
		self.assertIn('class="account-hierarchy"', html)
		for code, title in EXPECTED_PRINT_HIERARCHY:
			self.assertIn(code, html)
			self.assertIn(title, html)
		self.assertIn("AET Customer A", html)
		self.assertIn("AET Customer B", html)
		self.assertIn("AET Supplier A", html)
		self.assertIn("مرکز هزینه", html)
		self.assertIn("پروژه", html)
		self.assertTrue("تسهیلات" in html or "Facility" in html)
		self.assertIn("تراز", html)
		self.assertIn("140", html)  # Jalali year prefix
		report = {
			"gl_row_count": gl_count,
			"renderer_ms": round(elapsed_ms, 2),
			"html_size": len(html),
			"memory_peak_kb": round(peak / 1024, 1),
		}
		frappe.cache().set_value("aet_vgl_perf_report", report)
		self.assertLess(elapsed_ms, 5000)
		self.assertGreater(gl_count, 4)

	def test_raw_amount_lines_and_totals(self):
		v10 = next(v for v in self.ds["vouchers"] if v["key"] == "v10_amount_raw")
		html = self._render(v10["name"])
		self.assertIn("300,000", html)
		self.assertIn("700,000", html)
		self.assertIn("1,000,000", html)
		self.assertIn('class="currency-label"', html)
		self.assertIn('class="accounting-number"', html)
		self.assertRegex(
			html,
			r'currency-label[^>]*>ریال</span>\s*<span class="accounting-number"[^>]*>1,000,000</span>',
		)
		self.assertNotRegex(html, r"\d[\d,٫]*\s*هزار\s*ریال")
		self.assertNotRegex(html, r"\d[\d,٫]*\s*میلیون\s*ریال")
		self.assertNotRegex(html, r"\b1M\b|\b1K\b|\b1T\b")
		self.assertNotRegex(html, r"(?i)\b(million|thousand)\b")
		self.assertIn("totals-align-table", html)
		self.assertIn("hier-code", html)
		self.assertIn("hier-title", html)
		self.assertIn("جمع بدهکار", html)
		self.assertIn("جمع بستانکار", html)
		self.assertNotIn("جمع مبلغ جزء", html)
		self.assertIn("یک میلیون ریال", html)
		self.assertNotIn("ریال یک میلیون", html)
		# Resolved scale must remain Raw for this print
		from erpnext_extensions.iran_accounting.account_explorer.voucher_gl_renderer import (
			enrich_print_payload,
		)
		from erpnext_extensions.iran_accounting.account_explorer.voucher_gl_print import (
			build_voucher_gl_print,
		)

		payload = enrich_print_payload(
			build_voucher_gl_print(self._filters(v10["name"])), self._filters(v10["name"])
		)
		self.assertEqual(payload.get("resolved_amount_scale"), "raw")
		self.assertEqual(getattr(payload.get("amount_scale"), "scale", None), "raw")
