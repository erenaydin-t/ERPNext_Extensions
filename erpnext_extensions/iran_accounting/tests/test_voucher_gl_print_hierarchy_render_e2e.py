# Copyright (c) 2026, Farbod Siyahpoosh and contributors
"""Backend render E2E — production HTML must include Level-2→leaf hierarchy."""

from __future__ import annotations

import re
import unittest

import frappe

from erpnext_extensions.iran_accounting.account_explorer import api
from erpnext_extensions.iran_accounting.account_explorer.voucher_gl_print import build_voucher_gl_print
from erpnext_extensions.iran_accounting.account_explorer.voucher_gl_print_language import (
	SETTING_ENGLISH,
	SETTING_PERSIAN,
)
from erpnext_extensions.iran_accounting.account_explorer.voucher_gl_renderer import (
	enrich_print_payload,
)
from erpnext_extensions.iran_accounting.tests.voucher_gl_print_fixtures import (
	DEPTH_HIER_CODES,
	DEPTH_HIER_TITLES,
	ensure_depth_hierarchy_fixture,
	ensure_hierarchy_business_fixture,
	ensure_print_company,
)


class TestVoucherGLPrintHierarchyRenderE2E(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")

		class _Gate:
			@staticmethod
			def skipTest(msg):
				raise unittest.SkipTest(msg)

		cls.ctx = ensure_depth_hierarchy_fixture(
			ensure_hierarchy_business_fixture(ensure_print_company(_Gate()))
		)
		settings = frappe.get_single("Iran Accounting Settings")
		settings.voucher_gl_show_account_hierarchy = 1
		settings.voucher_gl_hierarchy_start_level = 2
		settings.voucher_gl_print_language = SETTING_PERSIAN
		settings.flags.ignore_permissions = True
		settings.save()
		frappe.db.commit()

	def _filters(self, **extra):
		base = {
			"company": self.ctx["company"],
			"voucher_type": "Journal Entry",
			"voucher_no": self.ctx["depth_je"],
			"layout": "Standard",
			"show_account_hierarchy": 1,
			"account_hierarchy_start_level": 2,
			"user_amount_scale": "Raw",
			"include_opening_entries": 1,
		}
		base.update(extra)
		return base

	def test_payload_rows_carry_print_hierarchy_contract(self):
		filters = self._filters()
		payload = enrich_print_payload(build_voucher_gl_print(filters), filters)
		leaf_rows = [r for r in payload["rows"] if r.get("account") == self.ctx["depth_leaf"]]
		self.assertTrue(leaf_rows)
		hier = leaf_rows[0].get("account_hierarchy") or []
		self.assertEqual(len(hier), 3)
		self.assertEqual([n["code"] for n in hier], list(DEPTH_HIER_CODES))
		self.assertEqual([n["name"] for n in hier], [DEPTH_HIER_TITLES[c] for c in DEPTH_HIER_CODES])
		self.assertEqual([n["level"] for n in hier], [2, 3, 4])
		self.assertNotEqual([n["code"] for n in hier], ["2101010001"])

	def test_api_html_contains_full_hierarchy_not_leaf_only(self):
		frappe.local.lang = "en"
		filters = self._filters()
		html = api.render_voucher_gl_print(
			company=filters["company"],
			voucher_type=filters["voucher_type"],
			voucher_no=filters["voucher_no"],
			filters=filters,
		)
		self.assertIn('class="account-hierarchy"', html)
		for code in DEPTH_HIER_CODES:
			self.assertIn(code, html)
		for title in DEPTH_HIER_TITLES.values():
			self.assertIn(title, html)
		self.assertRegex(
			html,
			r'acct-code">2101</span>[\s\S]*acct-code">210101</span>[\s\S]*acct-code">2101010001</span>',
		)
		# Prefer real tbody markup (CSS also mentions data-node="account_header").
		tbody = re.search(r"<tbody>([\s\S]*?)</tbody>", html)
		self.assertIsNotNone(tbody)
		body = tbody.group(1)
		first_header = re.search(
			r'<tr[^>]*data-node="account_header"[^>]*>([\s\S]*?)</tr>',
			body,
		)
		self.assertIsNotNone(first_header)
		header_chunk = first_header.group(1)
		self.assertIn("2101", header_chunk)
		self.assertIn("210101", header_chunk)
		self.assertIn("2101010001", header_chunk)
		self.assertIn('class="account-hierarchy"', header_chunk)
		codes = re.findall(r'class="acct-code"[^>]*>([^<]+)', header_chunk)
		names = re.findall(r'class="hier-title"[^>]*>([^<]+)', header_chunk)
		if not names:
			names = re.findall(r'class="acct-name"[^>]*>([^<]+)', header_chunk)
		self.assertEqual(codes, ["2101", "210101", "2101010001"])
		self.assertEqual(names, [DEPTH_HIER_TITLES[c] for c in DEPTH_HIER_CODES])
		# Forbid leaf-only hierarchy block for this account.
		self.assertNotEqual(codes, ["2101010001"])
		# Standard: codes in account column, titles in description (aligned levels).
		self.assertGreaterEqual(header_chunk.count("hier-code"), 3)
		self.assertGreaterEqual(header_chunk.count("hier-title"), 3)
		self.assertEqual(len(codes), len(names))

	def test_english_print_keeps_hierarchy_codes(self):
		settings = frappe.get_single("Iran Accounting Settings")
		settings.voucher_gl_print_language = SETTING_ENGLISH
		settings.flags.ignore_permissions = True
		settings.save()
		frappe.db.commit()
		try:
			frappe.local.lang = "fa"
			filters = self._filters()
			html = api.render_voucher_gl_print(
				company=filters["company"],
				voucher_type=filters["voucher_type"],
				voucher_no=filters["voucher_no"],
				filters=filters,
			)
			self.assertRegex(html, r'<html[^>]*dir="ltr"')
			for code in DEPTH_HIER_CODES:
				self.assertIn(code, html)
		finally:
			settings.voucher_gl_print_language = SETTING_PERSIAN
			settings.flags.ignore_permissions = True
			settings.save()
			frappe.db.commit()
