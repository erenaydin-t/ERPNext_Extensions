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
from frappe.utils import cint, flt, money_in_words

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


def enrich_print_payload(payload: dict, filters: dict | None = None) -> dict:
	"""Attach summary, amount-in-words, hierarchy groups, signatures, attachments."""
	from erpnext_extensions.iran_accounting.account_explorer.voucher_gl_hierarchy import (
		enrich_rows_with_hierarchy,
	)
	from erpnext_extensions.iran_accounting.account_explorer.voucher_gl_layout import (
		get_print_labels,
		resolve_print_language,
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
	labels = get_print_labels(resolve_print_language(filters))
	is_balanced = totals["is_balanced"]

	payload["summary"] = {
		"gl_row_count": len(rows),
		"total_debit": totals["total_debit"],
		"total_credit": totals["total_credit"],
		"difference": totals["difference"],
		"is_balanced": is_balanced,
		"balanced_label": (
			f"✔ {labels['balanced_ok']}" if is_balanced else f"✖ {labels['balanced_bad']}"
		),
		"currency": header.get("currency") or company_currency,
		"source_voucher": header.get("source_document"),
		"voucher_state": header.get("voucher_status") or _("Submitted"),
		"cancelled": has_cancelled,
		"opening_entry": has_opening,
		"finance_book": header.get("finance_book") or "",
		"print_meta_source": header.get("print_meta_source") or "",
	}
	# Amount in words ALWAYS from raw accounting total (never scaled visual).
	amount_words = ""
	try:
		amount_words = money_in_words(flt(totals["total_debit"]), company_currency) or ""
	except Exception:
		amount_words = ""
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
	scale_filters.setdefault("language", resolve_print_language(filters))
	# Print profile Amount Scale overrides Use Default → settings / user pref.
	if not scale_filters.get("amount_scale"):
		profile_scale = frappe.get_single_value("Iran Accounting Settings", "voucher_gl_amount_scale")
		if profile_scale:
			scale_filters["amount_scale"] = profile_scale
	amount_opts = resolve_print_amount_scale(scale_filters)
	# Freeze Auto once against voucher totals so all lines/subtotals/totals share one scale.
	from erpnext_extensions.iran_accounting.domain.amount_scale import (
		SCALE_AUTO,
		AmountScaleOptions,
		effective_scale,
	)
	from dataclasses import replace

	if amount_opts.scale == SCALE_AUTO:
		frozen = effective_scale(SCALE_AUTO, totals.get("total_debit") or 0)
		amount_opts = replace(amount_opts, scale=frozen)
	payload["amount_scale"] = amount_opts

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
		)

	context = {
		**payload,
		"print": print_ctx,
		"meta_rows": build_meta_rows(header, labels),
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
