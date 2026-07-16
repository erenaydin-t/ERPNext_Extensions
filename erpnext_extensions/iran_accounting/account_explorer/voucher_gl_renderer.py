# Copyright (c) 2026, Farbod Siyahpoosh and contributors
"""Reusable Voucher GL Renderer — Enterprise Accounting Voucher Package.

Built-in layouts: Standard, Modern, Compact (app-managed Jinja package).
Custom Print Format: desk report route only; one-click uses built-in package skin.

Custom layout does NOT inject arbitrary DocType Print Format HTML — those templates
assume transactional `doc` context and will leak raw Jinja if misused.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, cstr, flt, money_in_words

from erpnext_extensions.iran_accounting.account_explorer.voucher_gl_layout import (
	LAYOUT_AUDIT,
	LAYOUT_COMPACT,
	LAYOUT_CUSTOM,
	LAYOUT_MODERN,
	LAYOUT_STANDARD,
	assert_rendered_html_safe,
	build_meta_rows,
	build_print_context,
	format_amount,
	render_letterhead_html,
)
from erpnext_extensions.iran_accounting.account_explorer.voucher_gl_print import (
	DEFAULT_VOUCHER_GL_PRINT_FORMAT,
	_optional_qr_data_url,
	build_voucher_gl_print,
)

BUILT_IN_LAYOUTS = frozenset({LAYOUT_STANDARD, LAYOUT_MODERN, LAYOUT_COMPACT, LAYOUT_AUDIT})
LAYOUT_TEMPLATE = "templates/voucher_gl/package.html"


def resolve_voucher_gl_layout(filters: dict | None = None) -> str:
	filters = filters or {}
	if filters.get("layout"):
		return str(filters.get("layout"))
	layout = frappe.get_single_value("Iran Accounting Settings", "voucher_gl_layout")
	return layout or LAYOUT_STANDARD


def resolve_append_attachments(filters: dict | None = None) -> bool:
	filters = filters or {}
	if "append_source_attachments" in filters:
		return bool(cint(filters.get("append_source_attachments")))
	return bool(cint(frappe.get_single_value("Iran Accounting Settings", "append_source_attachments")))


def _looks_latin_money_words(text: str) -> bool:
	"""True when amount-in-words is English (do not mix into Persian vouchers)."""
	s = cstr(text or "").strip()
	if not s:
		return False
	latin = sum(1 for ch in s if ("A" <= ch <= "Z") or ("a" <= ch <= "z"))
	arabic = sum(1 for ch in s if "\u0600" <= ch <= "\u06FF")
	return latin > 0 and arabic == 0


def _reorder_persian_amount_in_words(words: str, currency_labels: list[str]) -> str:
	"""Frappe money_in_words emits «ریال یک میلیون»; accounting grammar wants «یک میلیون ریال»."""
	import re

	text = cstr(words).strip()
	if not text:
		return text
	labels = [cstr(x).strip() for x in currency_labels if cstr(x).strip()]
	# Prefer longer labels first (ریال before ر).
	labels = sorted(set(labels), key=len, reverse=True)
	for label in labels:
		escaped = re.escape(label)
		# فقط؟ + currency + number-words + optional trailing punctuation
		pattern = rf"^(فقط\s+)?{escaped}\s+(.+?)([.۔]?)\s*$"
		match = re.match(pattern, text, flags=re.DOTALL)
		if match:
			prefix, body, punct = match.group(1) or "", match.group(2).strip(), match.group(3) or ""
			# Drop a trailing currency already duplicated at the end of body.
			body = re.sub(rf"\s*{escaped}\s*$", "", body).strip()
			return f"{prefix}{body} {label}{punct}".strip()
	return text


def resolve_amount_in_words(amount, currency: str, lang: str) -> str:
	"""Amount in words from raw total; Persian mode never shows English-only text."""
	from erpnext_extensions.iran_accounting.account_explorer.voucher_gl_layout import (
		localize_currency_label,
	)

	prev = getattr(frappe.local, "lang", None) or "en"
	try:
		frappe.local.lang = lang or "en"
		words = money_in_words(flt(amount), currency) or ""
	except Exception:
		words = ""
	finally:
		frappe.local.lang = prev

	words = cstr(words).strip()
	if not words:
		return ""

	if lang in ("fa", "ar"):
		# Prefer localized currency label over ISO code in Persian output.
		safe = localize_currency_label(currency, lang) if currency else ""
		currency_labels = []
		if currency in ("IRR", "ریال") or safe == "ریال":
			words = words.replace("IRR", "ریال").replace("﷼", "ریال")
			currency_labels = ["ریال", "IRR", "﷼"]
		elif currency:
			# Keep ISO code but avoid lone Latin money phrases under FA voucher.
			words = words.replace("﷼", currency)
			currency_labels = [safe, currency, "﷼"] if safe else [currency, "﷼"]
		words = _reorder_persian_amount_in_words(words, currency_labels)
		# Hide if still Latin-only (English money words).
		if _looks_latin_money_words(words):
			return ""
		# Hide mixed junk like "فقط هزار INR." when number-words failed meaningfully.
		if currency and currency not in ("IRR", "ریال") and currency in words:
			# Allow ISO code with Persian number words; reject if no Persian digits/letters for numbers
			if not any("\u0600" <= ch <= "\u06FF" for ch in words):
				return ""
	return words


def enrich_print_payload(payload: dict, filters: dict | None = None) -> dict:
	"""Attach summary, amount-in-words, hierarchy groups, signatures, attachments."""
	from erpnext_extensions.iran_accounting.account_explorer.voucher_gl_hierarchy import (
		enrich_rows_with_hierarchy,
	)
	from erpnext_extensions.iran_accounting.account_explorer.voucher_gl_layout import (
		get_print_labels,
		localize_currency_label,
	)
	from erpnext_extensions.iran_accounting.account_explorer.voucher_gl_print_language import (
		localize_voucher_presentation,
		resolve_print_language_from_filters,
	)
	from erpnext_extensions.iran_accounting.domain.amount_scale import resolve_print_amount_scale

	filters = frappe._dict(filters or {})
	header = payload["header"]
	totals = payload["totals"]
	rows = payload["rows"]
	company_currency = (
		frappe.get_cached_value("Company", header["company"], "default_currency") or "INR"
	)
	precision = cint(frappe.db.get_default("currency_precision")) or 2

	has_cancelled = any(cint(r.get("is_cancelled")) for r in rows)
	has_opening = any((r.get("is_opening") or "No") == "Yes" for r in rows)
	lang = resolve_print_language_from_filters(filters)
	labels = get_print_labels(lang)
	is_balanced = totals["is_balanced"]

	# Localize print provenance for the selected print language (not session Desk lang).
	print_origin = labels.get("print_origin_explorer") or "Account Explorer"
	header["print_meta_source"] = print_origin

	currency = header.get("currency") or company_currency
	currency_label = localize_currency_label(
		company_currency if "," not in cstr(currency) else company_currency, lang
	)

	payload["summary"] = {
		"gl_row_count": len(rows),
		"total_debit": totals["total_debit"],
		"total_credit": totals["total_credit"],
		"difference": totals["difference"],
		"is_balanced": is_balanced,
		"balanced_label": (
			f"✔ {labels['balanced_ok']}" if is_balanced else f"✖ {labels['balanced_bad']}"
		),
		"currency": currency_label or currency,
		"source_voucher": header.get("source_document"),
		"voucher_state": localize_voucher_presentation(
			header.get("voucher_status") or _("Submitted"), "voucher_status", lang
		),
		"cancelled": has_cancelled,
		"opening_entry": has_opening,
		"finance_book": header.get("finance_book") or "",
		"print_meta_source": print_origin,
	}
	# Amount in words ALWAYS from raw accounting total (never scaled visual).
	amount_words = resolve_amount_in_words(totals["total_debit"], company_currency, lang)
	payload["totals"] = {
		**totals,
		"amount_in_words": amount_words,
	}
	payload["signatures"] = {
		"prepared_by": header.get("prepared_by") or "",
		"checked_by": "",
		"approved_by": "",
		"financial_manager": "",
		"accounting_manager": "",
	}
	payload["company_currency"] = company_currency
	payload["precision"] = precision
	payload["layout"] = resolve_voucher_gl_layout(filters)
	payload["append_source_attachments"] = resolve_append_attachments(filters)
	payload["attachments"] = []
	if payload["append_source_attachments"]:
		payload["attachments"] = collect_source_attachments(
			header.get("voucher_type"), header.get("voucher_no")
		)

	# Shared amount-scale contract for this print request.
	scale_filters = dict(filters)
	scale_filters.setdefault("currency", company_currency)
	scale_filters.setdefault("language", lang)
	# Print profile Amount Scale overrides Use Default → settings / user pref.
	if not scale_filters.get("amount_scale"):
		profile_scale = frappe.get_single_value("Iran Accounting Settings", "voucher_gl_amount_scale")
		if profile_scale:
			scale_filters["amount_scale"] = profile_scale
	amount_opts = resolve_print_amount_scale(scale_filters)
	# Auto means settings default (Raw when settings default is Auto/missing) — never magnitude pick.
	from erpnext_extensions.iran_accounting.domain.amount_scale import (
		SCALE_AUTO,
		SCALE_RAW,
		normalize_amount_scale,
		resolve_auto_to_settings_scale,
	)
	from dataclasses import replace

	requested_scale = normalize_amount_scale(amount_opts.scale, SCALE_RAW)
	if requested_scale == SCALE_AUTO:
		amount_opts = replace(amount_opts, scale=resolve_auto_to_settings_scale(SCALE_AUTO))
	else:
		amount_opts = replace(amount_opts, scale=requested_scale)
	payload["amount_scale"] = amount_opts
	payload["resolved_amount_scale"] = normalize_amount_scale(amount_opts.scale, SCALE_RAW)

	enrich_rows_with_hierarchy(payload, filters)
	return payload


def collect_source_attachments(voucher_type: str | None, voucher_no: str | None) -> list[dict]:
	if not voucher_type or not voucher_no or not frappe.db.exists(voucher_type, voucher_no):
		return []
	files = frappe.get_all(
		"File",
		filters={
			"attached_to_doctype": voucher_type,
			"attached_to_name": voucher_no,
			"is_folder": 0,
		},
		fields=["name", "file_name", "file_url", "is_private", "file_type"],
		order_by="creation asc",
	)
	out: list[dict] = []
	for f in files:
		name = (f.file_name or "").lower()
		url = f.file_url or ""
		is_image = name.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")) or (
			"image" in str(f.file_type or "").lower()
		)
		is_pdf = name.endswith(".pdf") or str(f.file_type or "").lower() == "pdf"
		if not (is_image or is_pdf):
			continue
		out.append(
			{
				"name": f.name,
				"file_name": f.file_name,
				"file_url": url,
				"kind": "image" if is_image else "pdf",
			}
		)
	return out


def render_voucher_package(filters) -> str:
	filters = frappe._dict(filters or {})
	layout = resolve_voucher_gl_layout(filters)
	payload = enrich_print_payload(build_voucher_gl_print(filters), filters)

	if layout == LAYOUT_CUSTOM:
		payload["layout"] = LAYOUT_CUSTOM
		payload["print_format"] = (
			filters.get("print_format")
			or frappe.get_single_value("Iran Accounting Settings", "voucher_gl_print_format")
			or DEFAULT_VOUCHER_GL_PRINT_FORMAT
		)
	elif layout not in BUILT_IN_LAYOUTS:
		layout = LAYOUT_STANDARD
		payload["layout"] = layout

	html = _render_builtin(payload, filters)
	assert_rendered_html_safe(html)
	return html


def _render_builtin(payload: dict, filters: dict) -> str:
	print_ctx = build_print_context(payload, filters)
	labels = print_ctx["labels"]
	header = payload["header"]
	payload["orientation"] = print_ctx["orientation"]
	payload["layout_direction"] = print_ctx["layout_direction"]

	def fmt_amount_cb(value):
		return format_amount(
			value,
			print_ctx["currency"],
			print_ctx["precision"],
			show_zero=print_ctx.get("show_zero_amounts"),
			amount_scale=print_ctx.get("amount_scale"),
			as_html=True,
		)

	context = {
		**payload,
		"print": print_ctx,
		"meta_rows": build_meta_rows(header, labels, lang=print_ctx["lang"]),
		"fmt_amount": fmt_amount_cb,
		"letterhead_html": "",
		"qr_data_url": None,
		"layout_class": f"vgl-layout-{(payload.get('layout') or LAYOUT_STANDARD).lower().replace(' ', '-')}",
	}
	# Letterhead only when settings/filters request it.
	if print_ctx.get("options", {}).get("show_letterhead"):
		lh_name = filters.get("letterhead") or frappe.db.get_default("letter_head")
		lh = render_letterhead_html(lh_name, header)
		if lh:
			try:
				assert_rendered_html_safe(lh)
				context["letterhead_html"] = lh
			except Exception:
				context["letterhead_html"] = ""

	# Attachments gated by print options
	if not print_ctx.get("options", {}).get("show_attachments"):
		context["attachments"] = []

	return frappe.render_template(LAYOUT_TEMPLATE, context)


def get_layout_options() -> list[dict[str, str]]:
	return [
		{"value": LAYOUT_STANDARD, "label": _("Standard")},
		{"value": LAYOUT_MODERN, "label": _("Modern")},
		{"value": LAYOUT_COMPACT, "label": _("Compact")},
		{"value": LAYOUT_AUDIT, "label": _("Audit")},
		{"value": LAYOUT_CUSTOM, "label": _("Custom Print Format (Desk report)")},
	]
