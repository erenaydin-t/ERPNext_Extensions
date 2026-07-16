# Copyright (c) 2026, Farbod Siyahpoosh and contributors
"""Shared accounting amount-scale formatter (grid + print + export metadata).

Scale never changes stored/raw GL totals. Amount-in-words always uses raw value.
CSV/XLSX numeric cells remain raw.
"""

from __future__ import annotations

from dataclasses import dataclass

import frappe
from frappe.utils import cint, cstr, flt


SCALE_RAW = "raw"
SCALE_AUTO = "auto"
SCALE_THOUSANDS = "thousands"
SCALE_MILLIONS = "millions"
SCALE_BILLIONS = "billions"
SCALE_TRILLIONS = "trillions"
SCALE_USE_DEFAULT = "use_default"

AMOUNT_SCALE_OPTIONS = (
	SCALE_RAW,
	SCALE_AUTO,
	SCALE_THOUSANDS,
	SCALE_MILLIONS,
	SCALE_BILLIONS,
	SCALE_TRILLIONS,
)

SCALE_DIVISORS = {
	SCALE_RAW: 1,
	SCALE_THOUSANDS: 1_000,
	SCALE_MILLIONS: 1_000_000,
	SCALE_BILLIONS: 1_000_000_000,
	SCALE_TRILLIONS: 1_000_000_000_000,
}

SCALE_LABELS_EN = {
	SCALE_THOUSANDS: "thousand",
	SCALE_MILLIONS: "million",
	SCALE_BILLIONS: "billion",
	SCALE_TRILLIONS: "trillion",
}

SCALE_LABELS_FA = {
	SCALE_THOUSANDS: "هزار",
	SCALE_MILLIONS: "میلیون",
	SCALE_BILLIONS: "میلیارد",
	SCALE_TRILLIONS: "تریلیون",
}


@dataclass(frozen=True)
class AmountScaleOptions:
	scale: str = SCALE_AUTO
	precision: int = 2
	currency: str = ""
	show_scale_label: bool = True
	locale: str = "en"


def normalize_amount_scale(value: str | None, fallback: str = SCALE_AUTO) -> str:
	scale = cstr(value or "").strip().lower().replace(" ", "_").replace("-", "_")
	aliases = {
		"use_default": SCALE_USE_DEFAULT,
		"usedefault": SCALE_USE_DEFAULT,
		"default": SCALE_USE_DEFAULT,
		"normal": SCALE_RAW,
	}
	scale = aliases.get(scale, scale)
	if scale == SCALE_USE_DEFAULT:
		return SCALE_USE_DEFAULT
	if scale in AMOUNT_SCALE_OPTIONS:
		return scale
	return fallback if fallback in AMOUNT_SCALE_OPTIONS else SCALE_RAW


def resolve_auto_scale(value) -> str:
	abs_value = abs(flt(value))
	if abs_value >= 1e12:
		return SCALE_TRILLIONS
	if abs_value >= 1e9:
		return SCALE_BILLIONS
	if abs_value >= 1e6:
		return SCALE_MILLIONS
	if abs_value >= 1e3:
		return SCALE_THOUSANDS
	return SCALE_RAW


def effective_scale(scale: str, value) -> str:
	"""Resolve display scale.

	``Auto`` no longer independently picks thousand/million by magnitude.
	Callers must map Auto → settings default first; leftover Auto becomes Raw.
	"""
	normalized = normalize_amount_scale(scale, SCALE_AUTO)
	if normalized == SCALE_AUTO:
		return SCALE_RAW
	if normalized == SCALE_USE_DEFAULT:
		return SCALE_RAW
	return normalized


def resolve_auto_to_settings_scale(scale: str | None = None) -> str:
	"""Map Auto / empty to Iran Accounting Settings default (Raw fallback)."""
	normalized = normalize_amount_scale(scale, SCALE_AUTO)
	if normalized != SCALE_AUTO and normalized in AMOUNT_SCALE_OPTIONS:
		return normalized
	setting = normalize_amount_scale(
		frappe.get_single_value("Iran Accounting Settings", "default_amount_display_scale"),
		SCALE_RAW,
	)
	if setting in (SCALE_AUTO, SCALE_USE_DEFAULT) or setting not in AMOUNT_SCALE_OPTIONS:
		return SCALE_RAW
	return setting


def scale_label(scale: str, *, locale: str = "en") -> str:
	eff = normalize_amount_scale(scale, SCALE_RAW)
	if eff in (SCALE_RAW, SCALE_AUTO, SCALE_USE_DEFAULT):
		return ""
	table = SCALE_LABELS_FA if cstr(locale).lower() in ("fa", "ar") else SCALE_LABELS_EN
	return table.get(eff, "")


def resolve_print_amount_scale(filters: dict | None = None) -> AmountScaleOptions:
	"""Priority for Voucher GL Print:

	1. Explicit print ``amount_scale`` (not Use Default)
	2. Iran Accounting Settings → Voucher GL Amount Scale (default Raw)
	3. Account Explorer ``user_amount_scale`` preference
	4. Iran Accounting Settings → Default Amount Display Scale
	5. Raw fallback

	Print profile Raw must not be overridden by AE Auto.
	"""
	filters = filters or {}
	if filters.get("amount_scale_precision") is None:
		precision = cint(
			frappe.get_single_value("Iran Accounting Settings", "amount_scale_decimal_precision") or 2
		)
	else:
		precision = cint(filters.get("amount_scale_precision"))
		if precision < 0:
			precision = 2

	show_label = filters.get("show_amount_scale_label")
	if show_label is None:
		show_label = frappe.get_single_value("Iran Accounting Settings", "show_amount_scale_label")
	if show_label is None or cstr(show_label).strip() == "":
		show_label = 1

	locale = cstr(filters.get("language") or getattr(frappe.local, "lang", None) or "en").lower()
	currency = cstr(filters.get("currency") or "")

	def _opts(scale: str) -> AmountScaleOptions:
		return AmountScaleOptions(
			scale=scale,
			precision=precision,
			currency=currency,
			show_scale_label=bool(cint(show_label)),
			locale=locale,
		)

	explicit = normalize_amount_scale(filters.get("amount_scale"), SCALE_USE_DEFAULT)
	if explicit != SCALE_USE_DEFAULT and explicit in AMOUNT_SCALE_OPTIONS:
		return _opts(explicit)

	# Print profile before AE grid preference so Raw print is not clobbered by Auto.
	profile = normalize_amount_scale(
		frappe.get_single_value("Iran Accounting Settings", "voucher_gl_amount_scale"),
		SCALE_RAW,
	)
	if profile != SCALE_USE_DEFAULT and profile in AMOUNT_SCALE_OPTIONS:
		return _opts(profile)

	user_pref = normalize_amount_scale(
		cstr(filters.get("user_amount_scale") or "").strip(), SCALE_USE_DEFAULT
	)
	if user_pref != SCALE_USE_DEFAULT and user_pref in AMOUNT_SCALE_OPTIONS:
		return _opts(user_pref)

	setting = normalize_amount_scale(
		frappe.get_single_value("Iran Accounting Settings", "default_amount_display_scale"),
		SCALE_RAW,
	)
	if setting == SCALE_USE_DEFAULT:
		setting = SCALE_RAW
	return _opts(setting if setting in AMOUNT_SCALE_OPTIONS else SCALE_RAW)


def _format_grouped_number(value: float, precision: int) -> str:
	"""Always produce #,### style grouping (ASCII commas). Never scale words."""
	prec = max(0, cint(precision))
	num = flt(value)
	sign = "-" if num < 0 else ""
	abs_v = abs(num)
	if prec <= 0 or abs(abs_v - round(abs_v)) < 1e-9:
		return f"{sign}{int(round(abs_v)):,}"
	whole = int(abs_v)
	frac = f"{abs_v:.{prec}f}".split(".")[-1]
	return f"{sign}{whole:,}.{frac}"


def _currency_word(currency: str, locale: str) -> str:
	currency = cstr(currency or "")
	if locale in ("fa", "ar") and currency in ("IRR", "ریال", ""):
		return "ریال"
	if currency in ("IRR", "ریال"):
		return "IRR" if locale not in ("fa", "ar") else "ریال"
	return currency


def build_amount_html(*, currency_label: str, number: str, locale: str) -> str:
	"""Explicit LTR amount stack so Persian visuals read «ریال 1,000,000»."""
	from frappe.utils import escape_html

	num = escape_html(number)
	if not currency_label:
		return f'<span class="accounting-amount" dir="ltr"><span class="accounting-number" dir="ltr">{num}</span></span>'
	cur = escape_html(currency_label)
	# Visual contract (FA): currency LEFT of digits → LTR flex with currency then number.
	if locale in ("fa", "ar"):
		return (
			f'<span class="accounting-amount" dir="ltr">'
			f'<span class="currency-label" dir="rtl">{cur}</span>'
			f" "
			f'<span class="accounting-number" dir="ltr">{num}</span>'
			f"</span>"
		)
	return (
		f'<span class="accounting-amount" dir="ltr">'
		f'<span class="accounting-number" dir="ltr">{num}</span>'
		f'<span class="currency-label">{cur}</span>'
		f"</span>"
	)


def format_accounting_amount(value, options: AmountScaleOptions | dict | None = None) -> dict:
	"""Shared contract used by print and Prefer grid alignment.

	Returns display (plain) and display_html (currency wrappers). Raw uses #,###.
	"""
	if isinstance(options, dict):
		options = AmountScaleOptions(
			scale=normalize_amount_scale(options.get("scale"), SCALE_AUTO),
			precision=cint(options.get("precision", 2)),
			currency=cstr(options.get("currency") or ""),
			show_scale_label=bool(options.get("show_scale_label", True)),
			locale=cstr(options.get("locale") or "en").lower(),
		)
	options = options or AmountScaleOptions()

	raw = flt(value)
	scale = normalize_amount_scale(options.scale, SCALE_AUTO)
	if scale == SCALE_AUTO:
		scale = resolve_auto_to_settings_scale(SCALE_AUTO)
	eff = effective_scale(scale, raw)
	divisor = SCALE_DIVISORS.get(eff, 1)
	scaled = raw / float(divisor) if divisor else raw
	prec = cint(options.precision)
	currency = options.currency or ""
	locale = options.locale
	currency_word = _currency_word(currency, locale)

	# IRR Raw / Auto→Raw: whole Rials without decimals.
	if eff == SCALE_RAW and currency in ("IRR", "ریال"):
		prec = 0

	if eff == SCALE_RAW:
		number = _format_grouped_number(raw, prec)
		if locale in ("fa", "ar") and currency_word:
			display = f"{currency_word} {number}"
		elif currency_word:
			display = f"{number} {currency_word}"
		else:
			display = number
		return {
			"raw": raw,
			"scaled": raw,
			"scale": SCALE_RAW,
			"display": display,
			"display_html": build_amount_html(
				currency_label=currency_word if currency_word else "",
				number=number,
				locale=locale,
			),
			"display_number": number,
			"scale_label": "",
			"currency": currency,
		}

	label = scale_label(eff, locale=locale) if options.show_scale_label else ""
	number = _format_grouped_number(scaled, prec if prec or prec == 0 else 2)
	parts = [number]
	if label:
		parts.append(label)
	if currency_word:
		parts.append(currency_word)
	display = " ".join(p for p in parts if p)
	# Scaled: keep plain; HTML mirrors plain text (no fake Raw currency order for non-Raw).
	escaped = display  # used as text; build minimal HTML
	from frappe.utils import escape_html

	return {
		"raw": raw,
		"scaled": scaled,
		"scale": eff,
		"display": display,
		"display_html": f'<span class="accounting-amount scaled" dir="ltr">{escape_html(display)}</span>',
		"display_number": number,
		"scale_label": label,
		"currency": currency,
	}
