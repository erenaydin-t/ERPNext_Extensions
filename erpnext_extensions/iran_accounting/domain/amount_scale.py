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
	normalized = normalize_amount_scale(scale, SCALE_AUTO)
	if normalized == SCALE_AUTO:
		return resolve_auto_scale(value)
	if normalized == SCALE_USE_DEFAULT:
		return SCALE_RAW
	return normalized


def scale_label(scale: str, *, locale: str = "en") -> str:
	eff = normalize_amount_scale(scale, SCALE_RAW)
	if eff in (SCALE_RAW, SCALE_AUTO, SCALE_USE_DEFAULT):
		return ""
	table = SCALE_LABELS_FA if cstr(locale).lower() in ("fa", "ar") else SCALE_LABELS_EN
	return table.get(eff, "")


def resolve_print_amount_scale(filters: dict | None = None) -> AmountScaleOptions:
	"""Priority: print filter → user AE preference → settings default → raw."""
	filters = filters or {}
	precision = cint(filters.get("amount_scale_precision"))
	if precision < 0:
		precision = cint(
			frappe.get_single_value("Iran Accounting Settings", "amount_scale_decimal_precision") or 2
		)
	if precision < 0:
		precision = 2

	show_label = filters.get("show_amount_scale_label")
	if show_label is None:
		show_label = frappe.get_single_value("Iran Accounting Settings", "show_amount_scale_label")
	if show_label is None or cstr(show_label).strip() == "":
		show_label = 1

	locale = cstr(filters.get("language") or getattr(frappe.local, "lang", None) or "en").lower()
	currency = cstr(filters.get("currency") or "")

	explicit = normalize_amount_scale(filters.get("amount_scale"), SCALE_USE_DEFAULT)
	if explicit != SCALE_USE_DEFAULT and explicit in AMOUNT_SCALE_OPTIONS:
		return AmountScaleOptions(
			scale=explicit,
			precision=precision if precision or precision == 0 else 2,
			currency=currency,
			show_scale_label=bool(cint(show_label)),
			locale=locale,
		)

	user_pref = cstr(filters.get("user_amount_scale") or "").strip()
	if not user_pref:
		# Optional hook: callers may pass Account Explorer grid preference.
		user_pref = ""
	user_pref = normalize_amount_scale(user_pref, SCALE_USE_DEFAULT)
	if user_pref != SCALE_USE_DEFAULT and user_pref in AMOUNT_SCALE_OPTIONS:
		return AmountScaleOptions(
			scale=user_pref,
			precision=precision if precision or precision == 0 else 2,
			currency=currency,
			show_scale_label=bool(cint(show_label)),
			locale=locale,
		)

	setting = normalize_amount_scale(
		frappe.get_single_value("Iran Accounting Settings", "default_amount_display_scale"),
		SCALE_AUTO,
	)
	if setting == SCALE_USE_DEFAULT:
		setting = SCALE_AUTO
	return AmountScaleOptions(
		scale=setting if setting in AMOUNT_SCALE_OPTIONS else SCALE_AUTO,
		precision=cint(
			frappe.get_single_value("Iran Accounting Settings", "amount_scale_decimal_precision") or 2
		)
		if filters.get("amount_scale_precision") is None
		else precision,
		currency=currency,
		show_scale_label=bool(cint(show_label)),
		locale=locale,
	)


def _format_number(value: float, precision: int) -> str:
	prec = max(0, cint(precision))
	# Avoid noisy trailing zeros for large scales; keep requested precision.
	formatted = frappe.utils.fmt_money(value, precision=prec)
	return formatted


def format_accounting_amount(value, options: AmountScaleOptions | dict | None = None) -> dict:
	"""Shared contract used by print and Prefer grid alignment.

	Returns:
	  {
	    "raw": float,
	    "scaled": float,
	    "scale": effective scale,
	    "display": "12 میلیون ریال",
	    "display_number": "12",
	    "scale_label": "میلیون",
	    "currency": "IRR",
	  }
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
	eff = effective_scale(options.scale, raw)
	divisor = SCALE_DIVISORS.get(eff, 1)
	scaled = raw / float(divisor) if divisor else raw
	prec = cint(options.precision)
	if eff == SCALE_RAW and options.currency in ("IRR", "ریال") and prec > 0:
		# IRR often prints without decimals when requested via print filters.
		pass
	number = _format_number(scaled, prec if eff != SCALE_RAW else prec)

	# For raw, prefer Frappe currency format when available.
	currency = options.currency or ""
	label = scale_label(eff, locale=options.locale) if options.show_scale_label else ""
	currency_word = currency
	if options.locale in ("fa", "ar") and currency in ("IRR", "ریال", ""):
		currency_word = "ریال" if currency in ("IRR", "ریال", "") else currency

	if eff == SCALE_RAW:
		if currency:
			try:
				display = frappe.format_value(
					raw, {"fieldtype": "Currency", "options": currency, "precision": prec}
				)
			except Exception:
				display = f"{number} {currency_word}".strip()
		else:
			display = number
		return {
			"raw": raw,
			"scaled": raw,
			"scale": SCALE_RAW,
			"display": display,
			"display_number": number,
			"scale_label": "",
			"currency": currency,
		}

	parts = [number]
	if label:
		parts.append(label)
	if currency_word and options.show_scale_label:
		parts.append(currency_word)
	elif currency_word and not options.show_scale_label:
		parts.append(currency_word)
	display = " ".join(p for p in parts if p)
	return {
		"raw": raw,
		"scaled": scaled,
		"scale": eff,
		"display": display,
		"display_number": number,
		"scale_label": label,
		"currency": currency,
	}
