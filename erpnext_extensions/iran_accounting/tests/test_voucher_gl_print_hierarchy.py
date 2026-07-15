# Copyright (c) 2026, Farbod Siyahpoosh and contributors
"""Voucher GL Print account hierarchy — level 2 through leaf."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import frappe
from frappe.utils import flt

from erpnext_extensions.iran_accounting.account_explorer.voucher_gl_hierarchy import (
	batch_resolve_account_hierarchies,
	group_print_rows,
)
from erpnext_extensions.iran_accounting.account_explorer.voucher_gl_layout import (
	LABELS_EN,
	LABELS_FA,
	build_hierarchy_code_html,
)
from erpnext_extensions.iran_accounting.account_explorer.voucher_gl_print import build_voucher_gl_print
from erpnext_extensions.iran_accounting.account_explorer.voucher_gl_renderer import (
	enrich_print_payload,
	render_voucher_package,
)
from erpnext_extensions.iran_accounting.account_explorer.voucher_gl_print_language import (
	SETTING_PERSIAN,
)
from erpnext_extensions.iran_accounting.tests.voucher_gl_print_fixtures import (
	DEPTH_HIER_CODES,
	DEPTH_HIER_TITLES,
	ensure_depth_hierarchy_fixture,
	ensure_hierarchy_business_fixture,
	ensure_print_company,
)


class TestVoucherGLPrintHierarchy(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")

		class _Gate:
			@staticmethod
			def skipTest(msg):
				raise unittest.SkipTest(msg)

		ctx = ensure_depth_hierarchy_fixture(
			ensure_hierarchy_business_fixture(ensure_print_company(_Gate()))
		)
		cls.ctx = ctx
		settings = frappe.get_single("Iran Accounting Settings")
		settings.voucher_gl_show_account_hierarchy = 1
		settings.voucher_gl_hierarchy_start_level = 2
		settings.voucher_gl_show_party_breakdown = 1
		settings.voucher_gl_show_dimension_breakdown = 1
		settings.voucher_gl_show_group_subtotals = 1
		settings.voucher_gl_print_language = SETTING_PERSIAN
		settings.flags.ignore_permissions = True
		settings.save()
		frappe.db.commit()

	def _depth_filters(self, **extra):
		base = {
			"company": self.ctx["company"],
			"voucher_type": "Journal Entry",
			"voucher_no": self.ctx["depth_je"],
			"layout": "Standard",
			"show_account_hierarchy": 1,
			"user_amount_scale": "Raw",
			"include_opening_entries": 1,
		}
		base.update(extra)
		return base

	def test_2101010001_prints_three_level_codes_and_titles(self):
		frappe.local.lang = "en"
		html = render_voucher_package(self._depth_filters())
		self.assertRegex(html, r'<html[^>]*lang="fa"')
		self.assertRegex(html, r'<html[^>]*dir="rtl"')
		for code in DEPTH_HIER_CODES:
			self.assertIn(code, html)
		for title in DEPTH_HIER_TITLES.values():
			self.assertIn(title, html)
		code_html = build_hierarchy_code_html(
			[
				{"account_number": c, "account_name": DEPTH_HIER_TITLES[c]}
				for c in DEPTH_HIER_CODES
			]
		)
		self.assertIn('dir="ltr"', code_html)
		self.assertIn("2101", code_html)
		self.assertIn("210101", code_html)
		self.assertIn("2101010001", code_html)

	def test_hierarchy_start_level_2_omits_root(self):
		payload = enrich_print_payload(build_voucher_gl_print(self._depth_filters()), self._depth_filters())
		leaf_rows = [r for r in payload["rows"] if r.get("account") == self.ctx["depth_leaf"]]
		self.assertTrue(leaf_rows)
		nums = [n.get("account_number") for n in leaf_rows[0].get("account_hierarchy") or []]
		self.assertIn("2101", nums)
		self.assertIn("210101", nums)
		self.assertIn("2101010001", nums)
		self.assertNotIn("21", nums)

	def test_titles_match_codes(self):
		payload = enrich_print_payload(build_voucher_gl_print(self._depth_filters()), self._depth_filters())
		hier = payload["rows"][0].get("account_hierarchy") or []
		by_num = {n["account_number"]: n["account_name"] for n in hier}
		for code, title in DEPTH_HIER_TITLES.items():
			self.assertEqual(by_num.get(code), title)

	def test_same_account_shows_hierarchy_once(self):
		payload = enrich_print_payload(build_voucher_gl_print(self._depth_filters()), self._depth_filters())
		nodes = payload.get("display_nodes") or []
		headers = [
			n
			for n in nodes
			if n.get("node_type") == "account_header" and n.get("account") == self.ctx["depth_leaf"]
		]
		self.assertEqual(len(headers), 1)
		self.assertEqual(
			len([n for n in nodes if n.get("node_type") == "gl_line" and n.get("account") == self.ctx["depth_leaf"]]),
			2,
		)

	def test_dimensions_remain_separated(self):
		payload = enrich_print_payload(build_voucher_gl_print(self._depth_filters()), self._depth_filters())
		nodes = payload.get("display_nodes") or []
		dim_headers = [n for n in nodes if n.get("node_type") == "dimension_header"]
		self.assertGreaterEqual(len(dim_headers), 1)

	def test_amount_totals_unchanged(self):
		payload = enrich_print_payload(build_voucher_gl_print(self._depth_filters()), self._depth_filters())
		self.assertEqual(flt(payload["totals"]["difference"], 9), 0)
		self.assertAlmostEqual(
			flt(payload["totals"]["total_debit"]),
			flt(payload["totals"]["total_credit"]),
			places=6,
		)

	def test_no_n_plus_one_account_load(self):
		company = self.ctx["company"]
		leaf = self.ctx["depth_leaf"]
		with patch(
			"erpnext_extensions.iran_accounting.account_explorer.voucher_gl_hierarchy.load_company_accounts"
		) as loader:
			loader.return_value = frappe.db.sql(
				"""
				select name, account_name, account_number, parent_account, is_group
				from `tabAccount`
				where company = %s
				""",
				company,
				as_dict=True,
			)
			batch_resolve_account_hierarchies(company, {leaf, self.ctx["hier_leaf"]}, start_level=2)
			self.assertEqual(loader.call_count, 1)

	def test_english_print_renders_code_title_pairs(self):
		settings = frappe.get_single("Iran Accounting Settings")
		settings.voucher_gl_print_language = "English"
		settings.flags.ignore_permissions = True
		settings.save()
		frappe.db.commit()
		try:
			frappe.local.lang = "fa"
			html = render_voucher_package(self._depth_filters())
			self.assertRegex(html, r'<html[^>]*lang="en"')
			self.assertIn(LABELS_EN["account_code"], html)
			self.assertIn(LABELS_EN["remarks"], html)
			for code in DEPTH_HIER_CODES:
				self.assertIn(code, html)
		finally:
			settings.voucher_gl_print_language = SETTING_PERSIAN
			settings.flags.ignore_permissions = True
			settings.save()
			frappe.db.commit()

	def test_parent_chain_party_split_reconciles(self):
		filters = {
			"company": self.ctx["company"],
			"voucher_type": "Journal Entry",
			"voucher_no": self.ctx["hier_je"],
			"show_account_hierarchy": 1,
			"user_amount_scale": "Raw",
			"include_opening_entries": 1,
		}
		payload = enrich_print_payload(build_voucher_gl_print(filters), filters)
		nodes = group_print_rows(payload["rows"], show_party=True, show_dimensions=True, show_subtotals=True)
		party_headers = [n for n in nodes if n.get("node_type") == "party_header"]
		self.assertGreaterEqual(len(party_headers), 2)
		account_sub = [n for n in nodes if n.get("node_type") == "account_subtotal"]
		self.assertTrue(account_sub)
		self.assertEqual(flt(account_sub[0]["debit"]), flt(payload["totals"]["total_debit"]))

	def test_parent_chain_resolution(self):
		company = self.ctx["company"]
		leaf = self.ctx["depth_leaf"]
		hier = batch_resolve_account_hierarchies(company, {leaf}, start_level=2).get(leaf, [])
		nums = [n.get("account_number") for n in hier]
		self.assertEqual(nums, list(DEPTH_HIER_CODES))

	def test_missing_parent_safety(self):
		company = self.ctx["company"]
		leaf = self.ctx["depth_leaf"]
		from erpnext_extensions.iran_accounting.account_explorer import voucher_gl_hierarchy as hier_mod

		def _empty_prefix(*args, **kwargs):
			return []

		with patch.object(hier_mod, "resolve_account_hierarchy_for_number", side_effect=_empty_prefix):
			hier = hier_mod.batch_resolve_account_hierarchies(company, {leaf}, start_level=2).get(leaf, [])
		nums = [n.get("account_number") for n in hier]
		self.assertIn("2101010001", nums)
		self.assertGreaterEqual(len(nums), 2)
		for code, title in DEPTH_HIER_TITLES.items():
			if code in nums:
				match = next(n for n in hier if n.get("account_number") == code)
				self.assertEqual(match.get("account_name"), title)

	def test_no_leaf_only_hierarchy_in_html(self):
		frappe.local.lang = "en"
		html = render_voucher_package(self._depth_filters())
		leaf = self.ctx["depth_leaf"]
		# Require stacked hierarchy beside titles — not a lone leaf code block.
		self.assertRegex(
			html,
			r'2101</span></div><div class="hier-code" dir="ltr"><span class="acct-code">210101',
		)
		self.assertIn("2101010001", html)
		self.assertIn(DEPTH_HIER_TITLES["2101"], html)
		# Leaf-only account groups (offset account) may have one code; depth leaf must not.
		depth_block = html.split(DEPTH_HIER_TITLES["2101"], 1)[0]
		self.assertGreaterEqual(depth_block.count("hier-code"), 3)

	def test_party_split(self):
		filters = {
			"company": self.ctx["company"],
			"voucher_type": "Journal Entry",
			"voucher_no": self.ctx["hier_je"],
			"show_account_hierarchy": 1,
			"user_amount_scale": "Raw",
			"include_opening_entries": 1,
		}
		payload = enrich_print_payload(build_voucher_gl_print(filters), filters)
		nodes = group_print_rows(payload["rows"], show_party=True, show_dimensions=True, show_subtotals=True)
		party_headers = [n for n in nodes if n.get("node_type") == "party_header"]
		self.assertGreaterEqual(len(party_headers), 2)
