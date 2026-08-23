# Copyright (c) 2026, Farbod Siyahpoosh and contributors
"""Voucher GL Print language — independent from Desk language."""

from __future__ import annotations

import inspect
import re
import unittest

import frappe
from frappe.utils import cint

from erpnext_extensions.iran_accounting.account_explorer.voucher_gl_layout import (
	LABELS_EN,
	LABELS_FA,
	build_print_context,
	build_print_dates,
	format_voucher_gl_print_date,
)
from erpnext_extensions.iran_accounting.account_explorer.voucher_gl_print_language import (
	PRINT_LANG_EN,
	PRINT_LANG_FA,
	SETTING_ENGLISH,
	SETTING_FOLLOW_USER,
	SETTING_PERSIAN,
	resolve_voucher_gl_print_language,
)
from erpnext_extensions.iran_accounting.account_explorer.voucher_gl_renderer import (
	enrich_print_payload,
	render_voucher_package,
)
from erpnext_extensions.iran_accounting.account_explorer.voucher_gl_print import build_voucher_gl_print
from frappe.utils import cstr
from erpnext_extensions.patches.post_model_sync.seed_voucher_gl_layout_settings import (
	PRINT_LANGUAGE_DEFAULT,
	_apply_print_language_default,
	apply_voucher_gl_print_defaults,
)
from erpnext_extensions.iran_accounting.tests.voucher_gl_print_fixtures import (
	ensure_print_company,
	ensure_print_dataset,
)


class TestVoucherGLPrintLanguage(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")

		class _Gate:
			@staticmethod
			def skipTest(msg):
				raise unittest.SkipTest(msg)

		cls.ctx = ensure_print_dataset(ensure_print_company(_Gate()))

	@classmethod
	def tearDownClass(cls):
		from erpnext_extensions.iran_accounting.tests.voucher_gl_print_fixtures import (
			cancel_print_fixture_jes,
		)

		cancel_print_fixture_jes(cls.ctx["company"])

	def setUp(self):
		settings = frappe.get_single("Iran Accounting Settings")
		self._orig_print_lang = settings.get("voucher_gl_print_language")
		self._orig_user_lang = frappe.local.lang
		settings.voucher_gl_print_language = SETTING_PERSIAN
		settings.flags.ignore_permissions = True
		settings.save()
		frappe.db.commit()

	def tearDown(self):
		settings = frappe.get_single("Iran Accounting Settings")
		settings.voucher_gl_print_language = self._orig_print_lang or SETTING_PERSIAN
		settings.flags.ignore_permissions = True
		settings.save()
		frappe.db.commit()
		if self._orig_user_lang:
			frappe.local.lang = self._orig_user_lang

	def _filters(self, **overrides):
		base = {
			"company": self.ctx["company"],
			"voucher_type": "Journal Entry",
			"voucher_no": self.ctx["je_multi"],
			"include_opening_entries": 1,
			"show_account_hierarchy": 0,
			"user_amount_scale": "Raw",
		}
		base.update(overrides)
		return base

	def _set_print_language(self, value: str | None):
		settings = frappe.get_single("Iran Accounting Settings")
		settings.voucher_gl_print_language = value
		settings.flags.ignore_permissions = True
		settings.save()
		frappe.db.commit()

	def _render(self, **filter_overrides):
		return render_voucher_package(self._filters(**filter_overrides))

	def test_english_desk_setting_persian_resolves_fa(self):
		frappe.local.lang = "en"
		self.assertEqual(
			resolve_voucher_gl_print_language(
				settings_language=SETTING_PERSIAN,
				user_language="en",
			),
			PRINT_LANG_FA,
		)

	def test_persian_desk_setting_english_resolves_en(self):
		frappe.local.lang = "fa"
		self.assertEqual(
			resolve_voucher_gl_print_language(
				settings_language=SETTING_ENGLISH,
				user_language="fa",
			),
			PRINT_LANG_EN,
		)

	def test_follow_user_english_desk(self):
		self.assertEqual(
			resolve_voucher_gl_print_language(
				settings_language=SETTING_FOLLOW_USER,
				user_language="en",
			),
			PRINT_LANG_EN,
		)

	def test_follow_user_persian_desk(self):
		self.assertEqual(
			resolve_voucher_gl_print_language(
				settings_language=SETTING_FOLLOW_USER,
				user_language="fa",
			),
			PRINT_LANG_FA,
		)

	def test_empty_setting_defaults_persian(self):
		self.assertEqual(
			resolve_voucher_gl_print_language(settings_language=None, user_language="en"),
			PRINT_LANG_FA,
		)

	def test_invalid_setting_defaults_persian(self):
		self.assertEqual(
			resolve_voucher_gl_print_language(settings_language="Deutsch", user_language="en"),
			PRINT_LANG_FA,
		)

	def test_explicit_fa_overrides_settings(self):
		self.assertEqual(
			resolve_voucher_gl_print_language(
				explicit_language="fa",
				settings_language=SETTING_ENGLISH,
				user_language="en",
			),
			PRINT_LANG_FA,
		)

	def test_explicit_en_overrides_settings(self):
		self.assertEqual(
			resolve_voucher_gl_print_language(
				explicit_language="en",
				settings_language=SETTING_PERSIAN,
				user_language="fa",
			),
			PRINT_LANG_EN,
		)

	def test_renderer_does_not_read_desk_lang_directly(self):
		layout_src = inspect.getsource(build_print_context)
		renderer_src = inspect.getsource(enrich_print_payload)
		self.assertNotIn("frappe.local.lang", layout_src)
		self.assertNotIn("frappe.local.lang", renderer_src)

	def test_package_html_lang_dir_from_resolved_print_language(self):
		self._set_print_language(SETTING_PERSIAN)
		frappe.local.lang = "en"
		html = self._render()
		self.assertRegex(html, r'<html[^>]*lang="fa"')
		self.assertRegex(html, r'<html[^>]*dir="rtl"')

		self._set_print_language(SETTING_ENGLISH)
		html_en = self._render()
		self.assertRegex(html_en, r'<html[^>]*lang="en"')
		self.assertRegex(html_en, r'<html[^>]*dir="ltr"')

	def test_persian_print_has_persian_headings(self):
		self._set_print_language(SETTING_PERSIAN)
		frappe.local.lang = "en"
		html = self._render()
		for label in (
			LABELS_FA["accounting_voucher"],
			LABELS_FA["voucher_number"],
			LABELS_FA["debit"],
			LABELS_FA["credit"],
			LABELS_FA["section_totals"],
		):
			self.assertIn(label, html)

	def test_english_print_has_english_headings(self):
		self._set_print_language(SETTING_ENGLISH)
		frappe.local.lang = "fa"
		html = self._render()
		for label in (
			LABELS_EN["accounting_voucher"],
			LABELS_EN["voucher_number"],
			LABELS_EN["debit"],
			LABELS_EN["credit"],
			LABELS_EN["section_totals"],
		):
			self.assertIn(label, html)

	def test_account_codes_remain_ltr_in_persian_print(self):
		self._set_print_language(SETTING_PERSIAN)
		html = self._render()
		self.assertIn('class="acct-code" dir="ltr"', html)

	def test_amounts_remain_ltr_in_persian_print(self):
		self._set_print_language(SETTING_PERSIAN)
		html = self._render()
		self.assertIn('class="col-amt text-end"', html)
		self.assertIn("direction: ltr", html)

	def test_source_voucher_print_setting_unchanged(self):
		settings = frappe.get_single("Iran Accounting Settings")
		orig = settings.get("show_print_voucher")
		settings.show_print_voucher = 0 if cint(orig) else 1
		settings.flags.ignore_permissions = True
		settings.save()
		frappe.db.commit()
		try:
			meta = frappe.get_meta("Iran Accounting Settings")
			self.assertTrue(meta.has_field("show_print_voucher"))
			self.assertTrue(meta.has_field("voucher_gl_print_language"))
		finally:
			settings.show_print_voucher = orig
			settings.flags.ignore_permissions = True
			settings.save()
			frappe.db.commit()

	def test_user_language_not_modified(self):
		frappe.local.lang = "en"
		before = frappe.db.get_value("User", frappe.session.user, "language")
		self._set_print_language(SETTING_PERSIAN)
		self._render()
		after = frappe.db.get_value("User", frappe.session.user, "language")
		self.assertEqual(before, after)
		self.assertEqual(frappe.local.lang, "en")

	def test_english_desk_persian_setting_runtime(self):
		frappe.local.lang = "en"
		self._set_print_language(SETTING_PERSIAN)
		html = self._render()
		self.assertIn(LABELS_FA["accounting_voucher"], html)
		self.assertNotIn(LABELS_EN["accounting_voucher"], html)

	def test_english_setting_runtime(self):
		frappe.local.lang = "fa"
		self._set_print_language(SETTING_ENGLISH)
		html = self._render()
		self.assertIn(LABELS_EN["accounting_voucher"], html)

	def test_follow_user_language_runtime(self):
		self._set_print_language(SETTING_FOLLOW_USER)
		frappe.local.lang = "en"
		html_en = self._render()
		self.assertIn(LABELS_EN["accounting_voucher"], html_en)
		frappe.local.lang = "fa"
		html_fa = self._render()
		self.assertIn(LABELS_FA["accounting_voucher"], html_fa)

	def test_migration_preserves_valid_existing_choice(self):
		settings = frappe.get_single("Iran Accounting Settings")
		settings.voucher_gl_print_language = SETTING_ENGLISH
		settings.flags.ignore_permissions = True
		settings.save()
		frappe.db.commit()
		changed = _apply_print_language_default(settings)
		self.assertFalse(changed)
		self.assertEqual(settings.voucher_gl_print_language, SETTING_ENGLISH)

	def test_migration_defaults_missing_choice_to_persian(self):
		settings = frappe.get_single("Iran Accounting Settings")
		settings.voucher_gl_print_language = ""
		settings.flags.ignore_permissions = True
		settings.save()
		frappe.db.commit()
		changed = _apply_print_language_default(settings)
		self.assertTrue(changed)
		self.assertEqual(settings.voucher_gl_print_language, PRINT_LANGUAGE_DEFAULT)

	def test_migration_invalid_resets_to_persian(self):
		frappe.db.sql(
			"""
			update tabSingles
			set value = %s
			where doctype = %s and field = %s
			""",
			("Deutsch", "Iran Accounting Settings", "voucher_gl_print_language"),
		)
		frappe.db.commit()
		settings = frappe.get_single("Iran Accounting Settings")
		changed = _apply_print_language_default(settings)
		self.assertTrue(changed)
		self.assertEqual(settings.voucher_gl_print_language, PRINT_LANGUAGE_DEFAULT)
		settings.flags.ignore_permissions = True
		settings.save()
		frappe.db.commit()

	def test_migrate_is_idempotent(self):
		settings = frappe.get_single("Iran Accounting Settings")
		settings.voucher_gl_print_language = SETTING_FOLLOW_USER
		settings.flags.ignore_permissions = True
		settings.save()
		frappe.db.commit()
		apply_voucher_gl_print_defaults(force=False)
		val_after_first = frappe.db.get_single_value(
			"Iran Accounting Settings", "voucher_gl_print_language"
		)
		apply_voucher_gl_print_defaults(force=False)
		val_after_second = frappe.db.get_single_value(
			"Iran Accounting Settings", "voucher_gl_print_language"
		)
		self.assertEqual(val_after_first, SETTING_FOLLOW_USER)
		self.assertEqual(val_after_second, SETTING_FOLLOW_USER)

	def test_persian_print_converts_dates_with_toshamshi(self):
		from persian_calendar.utils.jalali import toshamshi

		self._set_print_language(SETTING_PERSIAN)
		frappe.local.lang = "en"
		html = self._render()
		payload = enrich_print_payload(build_voucher_gl_print(self._filters()), self._filters())
		posting = payload["header"].get("posting_date")
		expected = toshamshi(posting, format="YYYY/MM/DD") if posting else ""
		self.assertTrue(expected)
		self.assertIn(expected, html)
		cover = html.split('data-section="gl-table"', 1)[0]
		self.assertNotIn(cstr(posting), cover)

	def test_english_print_keeps_gregorian_dates(self):
		self._set_print_language(SETTING_ENGLISH)
		frappe.local.lang = "fa"
		payload = enrich_print_payload(build_voucher_gl_print(self._filters()), self._filters())
		posting = cstr(payload["header"].get("posting_date") or "")
		dates = build_print_dates(payload["header"], PRINT_LANG_EN)
		self.assertEqual(dates.get("posting_date"), posting)
		html = self._render()
		if posting:
			self.assertIn(posting, html)

	def test_empty_date_does_not_fail(self):
		self.assertEqual(format_voucher_gl_print_date("", PRINT_LANG_FA), "")
		self.assertEqual(format_voucher_gl_print_date(None, PRINT_LANG_FA), "")
		ctx = build_print_context(
			{
				"header": {"posting_date": "", "print_timestamp": ""},
				"rows": [],
				"totals": {},
				"summary": {},
			},
			{"language": PRINT_LANG_FA},
		)
		self.assertEqual(ctx["dates"].get("posting_date"), "")
