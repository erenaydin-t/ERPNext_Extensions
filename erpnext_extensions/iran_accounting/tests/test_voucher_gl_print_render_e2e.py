# Copyright (c) 2026, Farbod Siyahpoosh and contributors
"""Backend E2E — render_voucher_gl_print API with real voucher fixture."""

from __future__ import annotations

import re
import unittest

import frappe

from erpnext_extensions.iran_accounting.account_explorer import api
from erpnext_extensions.iran_accounting.account_explorer.voucher_gl_print_language import (
	SETTING_ENGLISH,
	SETTING_PERSIAN,
)
from erpnext_extensions.iran_accounting.tests.voucher_gl_print_fixtures import (
	DEPTH_HIER_CODES,
	DEPTH_HIER_TITLES,
	ensure_depth_hierarchy_fixture,
	ensure_hierarchy_business_fixture,
	ensure_print_company,
)


class TestVoucherGLPrintRenderE2E(unittest.TestCase):
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
			"user_amount_scale": "Raw",
			"include_opening_entries": 1,
		}
		base.update(extra)
		return base

	def test_api_render_includes_full_hierarchy_and_jalali_dates(self):
		frappe.local.lang = "en"
		filters = self._filters()
		html = api.render_voucher_gl_print(
			company=filters["company"],
			voucher_type=filters["voucher_type"],
			voucher_no=filters["voucher_no"],
			filters=filters,
		)
		self.assertRegex(html, r'<html[^>]*lang="fa"')
		self.assertRegex(html, r'<html[^>]*dir="rtl"')
		for code in DEPTH_HIER_CODES:
			self.assertIn(code, html)
		for title in DEPTH_HIER_TITLES.values():
			self.assertIn(title, html)
		self.assertRegex(
			html,
			r'acct-code">2101</span>[\s\S]*acct-code">210101</span>[\s\S]*acct-code">2101010001</span>',
		)
		self.assertRegex(html, r"14\d{2}/\d{2}/\d{2}")
		posting = frappe.db.get_value("Journal Entry", self.ctx["depth_je"], "posting_date")
		if posting:
			cover = html.split('data-section="gl-table"', 1)[0]
			self.assertNotIn(str(posting), cover)

	def test_api_render_english_print_gregorian_dates(self):
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
			self.assertRegex(html, r'<html[^>]*lang="en"')
			self.assertRegex(html, r'<html[^>]*dir="ltr"')
			posting = frappe.db.get_value("Journal Entry", self.ctx["depth_je"], "posting_date")
			if posting:
				self.assertIn(str(posting), html)
		finally:
			settings.voucher_gl_print_language = SETTING_PERSIAN
			settings.flags.ignore_permissions = True
			settings.save()
			frappe.db.commit()
