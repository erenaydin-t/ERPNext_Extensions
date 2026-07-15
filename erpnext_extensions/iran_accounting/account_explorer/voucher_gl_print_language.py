# Copyright (c) 2026, Farbod Siyahpoosh and contributors
"""Server-authoritative Voucher GL Print language resolution.

Independent from Desk / Account Explorer UI language. Default: Persian (fa).
"""

from __future__ import annotations

import frappe
from frappe.utils import cstr

PRINT_LANG_FA = "fa"
PRINT_LANG_EN = "en"
FOLLOW_USER = "follow_user"

SETTING_PERSIAN = "Persian"
SETTING_ENGLISH = "English"
SETTING_FOLLOW_USER = "Follow User Language"

SETTINGS_TO_INTERNAL = {
	SETTING_PERSIAN.lower(): PRINT_LANG_FA,
	"persion": PRINT_LANG_FA,  # common typo guard
	SETTING_ENGLISH.lower(): PRINT_LANG_EN,
	SETTING_FOLLOW_USER.lower(): FOLLOW_USER,
	"follow user": FOLLOW_USER,
	"follow_user": FOLLOW_USER,
}

INTERNAL_ALIASES = {
	"fa": PRINT_LANG_FA,
	"ar": PRINT_LANG_FA,
	"persian": PRINT_LANG_FA,
	"farsi": PRINT_LANG_FA,
	"en": PRINT_LANG_EN,
	"english": PRINT_LANG_EN,
}

# Presentation-only labels for stored ERPNext values (Persian print mode).
VOUCHER_TYPE_FA = {
	"Journal Entry": "ثبت روزنامه",
	"Payment Entry": "سند پرداخت",
	"Sales Invoice": "فاکتور فروش",
	"Purchase Invoice": "فاکتور خرید",
	"Purchase Receipt": "رسید خرید",
	"Delivery Note": "حواله تحویل",
	"Stock Entry": "سند انبار",
	"Period Closing Voucher": "سند بستن دوره",
}

VOUCHER_STATUS_FA = {
	"Draft": "پیش‌نویس",
	"Submitted": "تأییدشده",
	"Cancelled": "لغوشده",
	"Unknown": "نامشخص",
}


def normalize_explicit_print_language(value) -> str | None:
	"""Map explicit request language to fa/en or None."""
	raw = cstr(value or "").strip().lower()
	if not raw:
		return None
	if raw in INTERNAL_ALIASES:
		return INTERNAL_ALIASES[raw]
	if raw in (PRINT_LANG_FA, PRINT_LANG_EN):
		return raw
	return None


def normalize_settings_print_language(value) -> str | None:
	"""Map Iran Accounting Settings Select value to fa/en/follow_user or None."""
	raw = cstr(value or "").strip()
	if not raw:
		return None
	key = raw.lower().replace("_", " ")
	if key in SETTINGS_TO_INTERNAL:
		return SETTINGS_TO_INTERNAL[key]
	if raw in SETTINGS_TO_INTERNAL:
		return SETTINGS_TO_INTERNAL[raw]
	# Stable internal storage if ever persisted directly.
	if raw in (PRINT_LANG_FA, PRINT_LANG_EN, FOLLOW_USER):
		return raw
	return None


def _resolve_user_language(user_language=None) -> str:
	lang = cstr(user_language or getattr(frappe.local, "lang", None) or "").lower()
	if not lang:
		lang = cstr(frappe.db.get_default("lang") or frappe.get_system_settings("language") or "en").lower()
	return PRINT_LANG_FA if lang in ("fa", "ar") else PRINT_LANG_EN


def resolve_voucher_gl_print_language(
	explicit_language=None,
	settings_language=None,
	user_language=None,
) -> str:
	"""Priority: explicit → settings → follow-user chain → Persian default."""
	explicit = normalize_explicit_print_language(explicit_language)
	if explicit in (PRINT_LANG_FA, PRINT_LANG_EN):
		return explicit

	setting = normalize_settings_print_language(settings_language)
	if setting == PRINT_LANG_FA:
		return PRINT_LANG_FA
	if setting == PRINT_LANG_EN:
		return PRINT_LANG_EN
	if setting == FOLLOW_USER:
		return _resolve_user_language(user_language)

	# Missing / empty / invalid → Persian business default.
	return PRINT_LANG_FA


def get_settings_print_language() -> str | None:
	"""Read configured Voucher GL Print Language from Iran Accounting Settings."""
	try:
		val = frappe.get_single_value("Iran Accounting Settings", "voucher_gl_print_language")
	except Exception:
		val = None
	return cstr(val or "").strip() or None


def resolve_print_language_from_filters(filters: dict | None = None) -> str:
	"""Convenience wrapper for renderer/layout — never reads Desk lang unless Follow User."""
	filters = filters or {}
	explicit = filters.get("language") or filters.get("print_language")
	settings = filters.get("voucher_gl_print_language") or get_settings_print_language()
	user_lang = filters.get("user_language")
	if user_lang is None and normalize_settings_print_language(settings) == FOLLOW_USER:
		user_lang = getattr(frappe.local, "lang", None)
	return resolve_voucher_gl_print_language(
		explicit_language=explicit,
		settings_language=settings,
		user_language=user_lang,
	)


def print_html_attrs(lang: str) -> dict[str, str]:
	"""Renderer contract: lang + dir for package root."""
	effective = PRINT_LANG_FA if lang in (PRINT_LANG_FA, "ar") else PRINT_LANG_EN
	return {
		"print_language": effective,
		"html_lang": effective,
		"html_dir": "rtl" if effective == PRINT_LANG_FA else "ltr",
		"rtl": effective == PRINT_LANG_FA,
	}


def localize_voucher_presentation(value, kind: str, lang: str) -> str:
	"""Presentation-only mapper; stored values unchanged."""
	text = cstr(value or "").strip()
	if not text or lang != PRINT_LANG_FA:
		return text
	if kind == "voucher_type":
		return VOUCHER_TYPE_FA.get(text, text)
	if kind == "voucher_status":
		return VOUCHER_STATUS_FA.get(text, text)
	return text
