# Copyright (c) 2026, Farbod Siyahpoosh and contributors
"""Voucher GL Print — layout profiles, i18n labels, column strategy, context composition.

Responsibility boundary (Wave 3B-3B.4):
- This module: profile selection, print context composition, columns, bilingual labels,
  RTL/LTR helpers, amount-cell presentation adapters.
- voucher_gl_hierarchy.py: account hierarchy + party/dimension grouping + subtotals.
- domain/amount_scale.py: shared scale resolve/format (grid + print).
- voucher_gl_renderer.py / package.html: package assemble + HTML emit.

No broad split this release — keep formatting adapters here to avoid churn risk.
"""

from __future__ import annotations

import re
from typing import Any

import frappe
from frappe import _
from frappe.utils import cint, cstr, flt, get_url

LAYOUT_STANDARD = "Standard"
LAYOUT_MODERN = "Modern"
LAYOUT_COMPACT = "Compact"
LAYOUT_AUDIT = "Audit"
LAYOUT_CUSTOM = "Custom Print Format"

PROFILE_STANDARD = "standard"
PROFILE_MODERN = "modern"
PROFILE_COMPACT = "compact"
PROFILE_FULL_AUDIT = "full_audit"

JINJA_MARKER_RE = re.compile(r"(\{%|\{\{|\}\}|%\})")

LABELS_FA = {
	"accounting_voucher": "سند حسابداری",
	"voucher_number": "شماره سند",
	"reference_number": "شماره عطف",
	"voucher_type": "نوع سند",
	"posting_date": "تاریخ سند",
	"posting_time": "زمان سند",
	"fiscal_year": "سال مالی",
	"finance_book": "دفتر مالی",
	"status": "وضعیت سند",
	"page": "صفحه",
	"source_document": "سند مبدأ",
	"voucher_description": "شرح سند",
	"party": "طرف حساب",
	"currency": "ارز",
	"prepared_by": "تهیه‌کننده",
	"printed_by": "چاپ‌کننده",
	"print_timestamp": "تاریخ و زمان چاپ",
	"print_date": "تاریخ چاپ",
	"gl_rows": "تعداد ردیف‌ها",
	"debit_total": "جمع کل بدهکار",
	"credit_total": "جمع کل بستانکار",
	"difference": "اختلاف",
	"balanced": "وضعیت تراز",
	"balanced_ok": "تراز",
	"balanced_bad": "عدم تراز",
	"source_voucher": "سند مبدأ",
	"voucher_state": "وضعیت سند",
	"cancelled": "ابطال‌شده",
	"opening_entry": "افتتاحیه",
	"row": "ردیف",
	"account_code": "کد حساب",
	"account_name": "عنوان حساب",
	"account_combined": "کد / عنوان حساب",
	"remarks": "شرح",
	"debit": "بدهکار",
	"credit": "بستانکار",
	"analytical_dimensions": "ابعاد تحلیلی",
	"against": "در مقابل",
	"account_currency": "ارز حساب",
	"opening": "افتتاحیه",
	"detail_ref": "مرجع جزئیات",
	"amount_in_words": "جمع به حروف",
	"debit_credit": "بدهکار / بستانکار",
	"checked_by": "بررسی‌کننده",
	"approved_by": "تأییدکننده",
	"financial_manager": "مدیر مالی",
	"accounting_manager": "رئیس حسابداری",
	"signature_date": "تاریخ",
	"signature_line": "امضا",
	"print": "چاپ",
	"close": "بستن",
	"layout": "قالب",
	"orientation": "جهت صفحه",
	"language": "زبان",
	"portrait": "عمودی",
	"landscape": "افقی",
	"persian": "فارسی",
	"english": "انگلیسی",
	"yes": "بله",
	"no": "خیر",
	"continuing_header": "ادامه سند",
	"print_meta": "چاپ از ERPNext حسابداری ایران",
	"phone": "تلفن",
	"attachment": "پیوست",
	"difference_short": "اختلاف",
	"generated_from": "محل چاپ",
	"print_origin_explorer": "مرور حساب",
	"name_field": "نام",
	"section_cover": "جلد سند",
	"section_info": "اطلاعات سند",
	"section_entries": "ثبت‌های حسابداری",
	"section_totals": "جمع کل",
	"section_approval": "تأیید و امضا",
	"line_amount": "مبلغ جزء",
	"subsidiary_amount": "مبلغ معین",
	"account_subtotal": "جمع حساب",
	"party_subtotal": "جمع طرف حساب",
	"dimension_subtotal": "جمع ابعاد تحلیلی",
	"party_type": "نوع طرف حساب",
	"party_name": "نام طرف حساب",
	"person": "شخص",
	"person_name": "نام شخص",
	"person_relation": "نوع ارتباط",
	"reference": "مرجع",
	"description_label": "شرح",
	"display_scale": "مقیاس نمایش",
	"supplier": "تأمین‌کننده",
	"customer": "مشتری",
	"employee": "کارمند",
	"layout_standard": "استاندارد",
	"layout_modern": "مدرن",
	"layout_compact": "فشرده",
	"layout_audit": "حسابرسی",
}

LABELS_EN = {
	"accounting_voucher": "Accounting Voucher",
	"voucher_number": "Voucher Number",
	"reference_number": "Reference Number",
	"voucher_type": "Voucher Type",
	"posting_date": "Posting Date",
	"posting_time": "Posting Time",
	"fiscal_year": "Fiscal Year",
	"finance_book": "Finance Book",
	"status": "Status",
	"page": "Page",
	"source_document": "Source Document",
	"voucher_description": "Voucher Description",
	"party": "Party",
	"currency": "Currency",
	"prepared_by": "Prepared By",
	"printed_by": "Printed By",
	"print_timestamp": "Print Date & Time",
	"print_date": "Print Date",
	"gl_rows": "GL Lines",
	"debit_total": "Total Debit",
	"credit_total": "Total Credit",
	"difference": "Difference",
	"balanced": "Balance Status",
	"balanced_ok": "Balanced",
	"balanced_bad": "Unbalanced",
	"source_voucher": "Source Voucher",
	"voucher_state": "Voucher State",
	"cancelled": "Cancelled",
	"opening_entry": "Opening",
	"row": "Row",
	"account_code": "Code",
	"account_name": "Account",
	"account_combined": "Code / Account",
	"remarks": "Description",
	"debit": "Debit",
	"credit": "Credit",
	"analytical_dimensions": "Analytical Dimensions",
	"against": "Against",
	"account_currency": "Account Currency",
	"opening": "Opening",
	"detail_ref": "Detail Ref",
	"amount_in_words": "Amount in Words",
	"debit_credit": "Debit / Credit",
	"checked_by": "Reviewed By",
	"approved_by": "Approved By",
	"financial_manager": "Financial Manager",
	"accounting_manager": "Chief Accountant",
	"signature_date": "Date",
	"signature_line": "Signature",
	"print": "Print",
	"close": "Close",
	"layout": "Layout",
	"orientation": "Orientation",
	"language": "Language",
	"portrait": "Portrait",
	"landscape": "Landscape",
	"persian": "Persian",
	"english": "English",
	"yes": "Yes",
	"no": "No",
	"continuing_header": "Continued",
	"print_meta": "Printed from ERPNext Iran Accounting",
	"phone": "Phone",
	"attachment": "Attachment",
	"difference_short": "Difference",
	"generated_from": "Generated From",
	"print_origin_explorer": "Account Explorer",
	"name_field": "Name",
	"section_cover": "Cover",
	"section_info": "Voucher Information",
	"section_entries": "Accounting Entries",
	"section_totals": "Totals",
	"section_approval": "Approval",
	"line_amount": "Line Amount",
	"subsidiary_amount": "Subsidiary Amount",
	"account_subtotal": "Account Subtotal",
	"party_subtotal": "Party Subtotal",
	"dimension_subtotal": "Dimension Subtotal",
	"party_type": "Party Type",
	"party_name": "Party Name",
	"person": "Person",
	"person_name": "Person Name",
	"person_relation": "Relation Type",
	"reference": "Reference",
	"description_label": "Description",
	"display_scale": "Display Scale",
	"supplier": "Supplier",
	"customer": "Customer",
	"employee": "Employee",
	"layout_standard": "Standard",
	"layout_modern": "Modern",
	"layout_compact": "Compact",
	"layout_audit": "Audit",
}


def resolve_print_language(filters: dict | None = None) -> str:
	filters = filters or {}
	if filters.get("language"):
		return cstr(filters["language"]).lower()
	lang = (frappe.local.lang or "en").lower()
	return "fa" if lang in ("fa", "ar") else "en"


def is_rtl_language(lang: str) -> bool:
	return lang in ("fa", "ar")


def get_print_labels(lang: str) -> dict[str, str]:
	return LABELS_FA if lang == "fa" else LABELS_EN


def resolve_column_profile(layout: str, filters: dict | None = None) -> str:
	filters = filters or {}
	if filters.get("column_profile"):
		return cstr(filters["column_profile"]).lower()
	if layout in (LAYOUT_AUDIT, "Full Audit") or cint(filters.get("full_audit_columns")):
		return PROFILE_FULL_AUDIT
	if layout == LAYOUT_COMPACT:
		return PROFILE_COMPACT
	if layout == LAYOUT_MODERN:
		return PROFILE_MODERN
	if layout == LAYOUT_CUSTOM:
		return PROFILE_STANDARD
	return PROFILE_STANDARD


def should_combine_dimensions(
	profile: str,
	dimensions: list[dict],
	*,
	force_full_audit: bool = False,
	combine_override: bool | None = None,
) -> bool:
	"""Standard/Modern/Compact combine by default; Audit never combines."""
	if force_full_audit or profile == PROFILE_FULL_AUDIT:
		return False
	if combine_override is not None:
		return bool(combine_override)
	return True


def resolve_orientation(
	profile: str,
	dimensions: list[dict],
	*,
	combine_dimensions: bool,
	page_layout: str = "Auto",
) -> str:
	page_layout = cstr(page_layout or "Auto")
	if page_layout in ("Portrait", "Landscape"):
		return page_layout
	if profile == PROFILE_FULL_AUDIT:
		return "Landscape"
	if profile == PROFILE_COMPACT:
		return "Portrait"
	if combine_dimensions:
		return "Portrait"
	active = [d for d in dimensions if d.get("fieldname")]
	if len(active) > 2:
		return "Landscape"
	return "Portrait"


def format_amount(
	value,
	currency: str,
	precision: int,
	*,
	show_zero: bool = False,
	amount_scale=None,
) -> str:
	amount = flt(value)
	if not show_zero and abs(amount) < 1e-12:
		return ""
	if amount_scale is not None:
		from erpnext_extensions.iran_accounting.domain.amount_scale import format_accounting_amount

		opts = amount_scale
		if hasattr(opts, "currency") and not opts.currency:
			from dataclasses import replace

			opts = replace(opts, currency=currency)
		return format_accounting_amount(amount, opts)["display"]
	prec = cint(precision)
	if currency in ("IRR", "ریال") and prec <= 0:
		prec = 0
	formatted = frappe.format_value(amount, {"fieldtype": "Currency", "precision": prec})
	# Strip unsafe currency glyphs — prefer bare number (CSV/legacy callers).
	for glyph in ("﷼", "₹", "$", "€", "£"):
		formatted = formatted.replace(glyph, "")
	formatted = formatted.strip()
	if currency == "IRR" and prec == 0 and formatted.endswith(".00"):
		formatted = formatted[:-3]
	return formatted


def escape_text(value) -> str:
	return frappe.utils.escape_html(cstr(value or ""))


def _dimension_display_label(dim: dict, *, rtl: bool = False) -> str:
	if rtl and dim.get("label_fa"):
		return cstr(dim.get("label_fa"))
	return cstr(dim.get("label") or dim.get("fieldname") or "")


def format_dimension_lines(
	row: dict, dimensions: list[dict], labels: dict[str, str] | None = None, *, rtl: bool = False
) -> str:
	lines: list[str] = []
	for dim in dimensions:
		fieldname = dim.get("fieldname")
		if not fieldname:
			continue
		info = (row.get("dimensions") or {}).get(fieldname) or {}
		value = info.get("title") or info.get("value") or ""
		if not value:
			continue
		dim_label = _dimension_display_label(dim, rtl=rtl)
		lines.append(f"{dim_label}: {value}")
	if not lines:
		return ""
	return "\n".join(lines)


def format_dimension_html(
	row: dict, dimensions: list[dict], labels: dict[str, str] | None = None, *, rtl: bool = False
) -> str:
	parts: list[str] = []
	for dim in dimensions:
		fieldname = dim.get("fieldname")
		if not fieldname:
			continue
		info = (row.get("dimensions") or {}).get(fieldname) or {}
		value = info.get("title") or info.get("value") or ""
		if not value:
			continue
		dim_label = escape_text(_dimension_display_label(dim, rtl=rtl))
		parts.append(
			'<span class="dim-line" dir="auto">'
			f'<span class="dim-k">{dim_label}:</span> '
			f'<bdi class="dim-v">{escape_text(value)}</bdi>'
			"</span>"
		)
	if not parts:
		return ""
	return '<div class="dim-block">' + "".join(parts) + "</div>"


def format_remarks_secondary(
	row: dict, labels: dict[str, str], *, compact: bool, standard: bool = False
) -> str:
	parts: list[str] = []
	if compact:
		if row.get("against"):
			parts.append(f"{labels['against']}: {row['against']}")
		if row.get("account_currency"):
			parts.append(f"{labels['account_currency']}: {row['account_currency']}")
	elif not standard:
		if row.get("against"):
			parts.append(f"{labels['against']}: {row['against']}")
		if row.get("account_currency"):
			parts.append(f"{labels['account_currency']}: {row['account_currency']}")
	if row.get("is_opening") == "Yes":
		parts.append(f"{labels['opening']}: {labels['yes']}")
	if cint(row.get("is_cancelled")):
		parts.append(f"{labels['cancelled']}: {labels['yes']}")
	if row.get("voucher_detail_no"):
		parts.append(f"{labels['detail_ref']}: {row['voucher_detail_no']}")
	if compact:
		party = row.get("party_name") or row.get("party")
		if party:
			parts.append(f"{labels['party']}: {party}")
	return "\n".join(parts)


def _party_type_label(party_type: str, labels: dict[str, str], *, kind: str = "party") -> str:
	"""Business Persian/English label for party type — never empty technical jargon."""
	pt = cstr(party_type or "").strip()
	mapping = {
		"Supplier": labels.get("supplier") or labels.get("party"),
		"Customer": labels.get("customer") or labels.get("party"),
		"Employee": labels.get("employee") or labels.get("person"),
	}
	if pt in mapping and mapping[pt]:
		return mapping[pt]
	if kind == "person":
		return labels.get("person") or labels.get("party")
	return labels.get("party") or "Party"


def build_hierarchy_code_html(hierarchy: list[dict] | None, *, leaf_fallback: str = "") -> str:
	"""Stacked LTR account codes for the کد حساب column (Level-N → leaf)."""
	parts: list[str] = []
	seen: set[str] = set()
	for level in hierarchy or []:
		code = cstr(level.get("account_number") or "").strip()
		if not code or code in seen:
			continue
		seen.add(code)
		parts.append(f'<div class="hier-code" dir="ltr"><span class="acct-code">{escape_text(code)}</span></div>')
	if not parts and leaf_fallback:
		parts.append(
			f'<div class="hier-code" dir="ltr"><span class="acct-code">{escape_text(leaf_fallback)}</span></div>'
		)
	return "".join(parts)


def build_hierarchy_description_html(
	node: dict,
	labels: dict[str, str],
	*,
	rtl: bool,
	show_hierarchy_in_cell: bool = True,
) -> str:
	"""Build semantic شرح cell: titles / party / dims / remarks (no technical empty labels)."""
	parts: list[str] = []
	node_type = node.get("node_type")
	if node_type == "account_header":
		# Titles only — codes live in the code column.
		hierarchy = node.get("account_hierarchy") or []
		for depth, level in enumerate(hierarchy):
			name = escape_text(level.get("account_name") or "")
			if not name:
				continue
			indent = depth * 12
			parts.append(
				f'<div class="hier-level" style="padding-inline-start:{indent}px">'
				f'<span class="acct-name" dir="auto" style="unicode-bidi:plaintext">{name}</span>'
				f"</div>"
			)
		return "".join(parts) or escape_text(node.get("account_name") or "")

	if node_type in ("party_header",):
		party = node.get("party") or {}
		party_name = cstr(party.get("party_name") or "").strip()
		if not party_name:
			return ""
		if party.get("kind") == "person":
			role = _party_type_label(party.get("party_type"), labels, kind="person")
			parts.append(
				f'<div class="party-block"><span class="dim-k">{escape_text(role)}:</span> '
				f'<span dir="auto" style="unicode-bidi:plaintext">{escape_text(party_name)}</span></div>'
			)
			rel = cstr(party.get("party_type") or "").strip()
			# Show relation type only when it differs from the role label itself.
			if rel and rel not in ("Employee",) and role == labels.get("person"):
				parts.append(
					f'<div class="party-block"><span class="dim-k">{escape_text(labels["person_relation"])}:</span> '
					f"{escape_text(rel)}</div>"
				)
			elif rel == "Employee" and labels.get("employee"):
				pass  # role already says کارمند / Employee
		else:
			role = _party_type_label(party.get("party_type"), labels, kind="party")
			parts.append(
				f'<div class="party-block"><span class="dim-k">{escape_text(role)}:</span> '
				f'<span dir="auto" style="unicode-bidi:plaintext">{escape_text(party_name)}</span></div>'
			)
		return "".join(parts)

	if node_type == "dimension_header":
		for dim in node.get("dimensions") or []:
			label = cstr(dim.get("label") or "").strip()
			value = cstr(dim.get("value") or "").strip()
			if not label or not value:
				continue
			parts.append(
				f'<div class="dim-line" dir="auto"><span class="dim-k">{escape_text(label)}:</span> '
				f'<bdi class="dim-v">{escape_text(value)}</bdi></div>'
			)
		return ('<div class="dim-block">' + "".join(parts) + "</div>") if parts else ""

	if node_type in ("account_subtotal", "party_subtotal", "dimension_subtotal"):
		label_key = {
			"account_subtotal": "account_subtotal",
			"party_subtotal": "party_subtotal",
			"dimension_subtotal": "dimension_subtotal",
		}[node_type]
		return f'<div class="subtotal-label">{escape_text(labels[label_key])}</div>'

	# gl_line — dims (if not already headed) then remarks; no "Description:" prefix.
	_ = show_hierarchy_in_cell  # reserved for compact embeds
	for dim in node.get("dimensions") or []:
		label = cstr(dim.get("label") or "").strip()
		value = cstr(dim.get("value") or "").strip()
		if not label or not value:
			continue
		parts.append(
			f'<div class="dim-line" dir="auto"><span class="dim-k">{escape_text(label)}:</span> '
			f'<bdi class="dim-v">{escape_text(value)}</bdi></div>'
		)
	desc = node.get("description") or {}
	main = cstr(desc.get("main") or "").strip()
	ref = cstr(desc.get("reference") or "").strip()
	if main:
		parts.append(
			f'<div class="remarks-main" dir="auto" style="unicode-bidi:plaintext">'
			f"{escape_text(main)}</div>"
		)
	if ref and ref != main:
		parts.append(
			f'<div class="remarks-sub" dir="auto" style="unicode-bidi:plaintext">'
			f'{escape_text(labels["reference"])}: {escape_text(ref)}</div>'
		)
	if not parts:
		parts.append('<div class="remarks-main"></div>')
	return "".join(parts)


def build_table_columns(
	profile: str,
	dimensions: list[dict],
	labels: dict[str, str],
	*,
	combine_dimensions: bool,
	hierarchical: bool = False,
) -> list[dict[str, Any]]:
	cols: list[dict[str, Any]] = [{"id": "idx", "label": labels["row"], "cls": "col-idx text-center"}]

	if hierarchical and profile != PROFILE_FULL_AUDIT:
		# Persian Standard hierarchical columns.
		cols.extend(
			[
				{"id": "account_code", "label": labels["account_code"], "cls": "col-account"},
				{"id": "remarks", "label": labels["remarks"], "cls": "col-remarks"},
				{"id": "line_amount", "label": labels["line_amount"], "cls": "col-amt text-end"},
				{"id": "debit", "label": labels["debit"], "cls": "col-amt text-end"},
				{"id": "credit", "label": labels["credit"], "cls": "col-amt text-end"},
			]
		)
		return cols

	if profile == PROFILE_COMPACT:
		cols.extend(
			[
				{"id": "account_stacked", "label": labels["account_combined"], "cls": "col-account"},
				{"id": "remarks", "label": labels["remarks"], "cls": "col-remarks"},
				{"id": "debit", "label": labels["debit"], "cls": "col-amt text-end"},
				{"id": "credit", "label": labels["credit"], "cls": "col-amt text-end"},
			]
		)
		return cols

	# Standard / Modern — binder columns only; account code+title stacked.
	cols.extend(
		[
			{"id": "account_stacked", "label": labels["account_combined"], "cls": "col-account"},
			{"id": "remarks", "label": labels["remarks"], "cls": "col-remarks"},
			{"id": "debit", "label": labels["debit"], "cls": "col-amt text-end"},
			{"id": "credit", "label": labels["credit"], "cls": "col-amt text-end"},
		]
	)
	if profile in (PROFILE_STANDARD, PROFILE_MODERN):
		cols.append({"id": "party", "label": labels["party"], "cls": "col-party"})
		if combine_dimensions:
			cols.append(
				{
					"id": "dimensions_combined",
					"label": labels["analytical_dimensions"],
					"cls": "col-dims",
				}
			)
		else:
			for dim in dimensions:
				cols.append(
					{
						"id": f"dim_{dim['fieldname']}",
						"label": dim.get("label") or dim["fieldname"],
						"cls": "col-dim",
					}
				)
		return cols

	# Full audit — wide export mode
	cols.extend(
		[
			{"id": "account_currency", "label": labels["account_currency"], "cls": "col-cur"},
			{"id": "debit_ac", "label": f"{labels['debit']} (AC)", "cls": "col-amt text-end"},
			{"id": "credit_ac", "label": f"{labels['credit']} (AC)", "cls": "col-amt text-end"},
			{"id": "party_type", "label": labels.get("party_type", "Party Type"), "cls": "col-party"},
			{"id": "party", "label": labels["party"], "cls": "col-party"},
			{"id": "against", "label": labels["against"], "cls": "col-against"},
		]
	)
	for dim in dimensions:
		cols.append(
			{
				"id": f"dim_{dim['fieldname']}",
				"label": dim.get("label") or dim["fieldname"],
				"cls": "col-dim",
			}
		)
	cols.extend(
		[
			{"id": "opening", "label": labels["opening"], "cls": "col-flag text-center"},
			{"id": "cancelled", "label": labels["cancelled"], "cls": "col-flag text-center"},
			{"id": "detail_ref", "label": labels["detail_ref"], "cls": "col-ref"},
		]
	)
	return cols


def column_has_any_value(col_id: str, rows: list[dict], dimensions: list[dict]) -> bool:
	"""True if at least one row has a non-empty value for the column."""
	for row in rows or []:
		if col_id == "party":
			if cstr(row.get("party_name") or row.get("party") or "").strip():
				return True
		elif col_id == "against":
			if cstr(row.get("against") or "").strip():
				return True
		elif col_id == "dimensions_combined":
			for dim in dimensions:
				info = (row.get("dimensions") or {}).get(dim.get("fieldname") or "") or {}
				if cstr(info.get("title") or info.get("value") or "").strip():
					return True
		elif col_id.startswith("dim_"):
			fieldname = col_id[4:]
			info = (row.get("dimensions") or {}).get(fieldname) or {}
			if cstr(info.get("title") or info.get("value") or "").strip():
				return True
		elif col_id == "opening":
			if (row.get("is_opening") or "No") == "Yes":
				return True
		elif col_id == "cancelled":
			if cint(row.get("is_cancelled")):
				return True
		elif col_id == "detail_ref":
			if cstr(row.get("voucher_detail_no") or "").strip():
				return True
		elif col_id in ("account_currency", "party_type"):
			if cstr(row.get(col_id) or "").strip():
				return True
		elif col_id in ("debit_ac", "credit_ac"):
			key = "debit_in_account_currency" if col_id == "debit_ac" else "credit_in_account_currency"
			if abs(flt(row.get(key))) > 1e-12:
				return True
	return False


OPTIONAL_HIDE_COLUMNS = frozenset(
	{
		"party",
		"against",
		"dimensions_combined",
		"party_type",
		"account_currency",
		"debit_ac",
		"credit_ac",
		"opening",
		"cancelled",
		"detail_ref",
	}
)


def filter_empty_columns(columns: list[dict], rows: list[dict], dimensions: list[dict], *, hide_empty: bool) -> list[dict]:
	if not hide_empty:
		return columns
	kept: list[dict] = []
	for col in columns:
		col_id = col["id"]
		if col_id.startswith("dim_") or col_id in OPTIONAL_HIDE_COLUMNS:
			if not column_has_any_value(col_id, rows, dimensions):
				continue
		kept.append(col)
	return kept


def resolve_company_contact(company: str) -> dict[str, str]:
	if not company:
		return {"address": "", "phone": ""}
	fields = ["address", "phone_no", "email", "website"]
	meta = frappe.get_meta("Company")
	available = [f for f in fields if meta.has_field(f)]
	values = frappe.db.get_value("Company", company, available, as_dict=True) or {}
	address = cstr(values.get("address") or "").strip()
	phone = cstr(values.get("phone_no") or "").strip()
	# Prefer linked Company Address if address field blank
	if not address and frappe.db.exists("Dynamic Link", {"link_doctype": "Company", "link_name": company, "parenttype": "Address"}):
		addr_name = frappe.db.get_value(
			"Dynamic Link",
			{"link_doctype": "Company", "link_name": company, "parenttype": "Address"},
			"parent",
		)
		if addr_name:
			addr = frappe.db.get_value(
				"Address",
				addr_name,
				["address_line1", "address_line2", "city", "state", "pincode", "country"],
				as_dict=True,
			) or {}
			parts = [addr.get("address_line1"), addr.get("address_line2"), addr.get("city"), addr.get("state"), addr.get("pincode")]
			address = ", ".join(cstr(p).strip() for p in parts if cstr(p).strip())
			if not phone:
				phone = cstr(frappe.db.get_value("Address", addr_name, "phone") or "").strip()
	return {"address": address, "phone": phone}


def resolve_print_options(filters: dict | None = None) -> dict:
	"""Merge Iran Accounting Settings with request filters for UX print toggles."""
	filters = filters or {}

	def _opt(filter_key: str, setting_key: str, default: int = 1) -> bool:
		if filter_key in filters:
			return bool(cint(filters.get(filter_key)))
		val = frappe.get_single_value("Iran Accounting Settings", setting_key)
		if val is None or cstr(val).strip() == "":
			return bool(default)
		return bool(cint(val))

	page_layout = cstr(filters.get("page_layout") or "").strip()
	if not page_layout:
		page_layout = cstr(
			frappe.get_single_value("Iran Accounting Settings", "voucher_gl_page_layout") or "Auto"
		).strip() or "Auto"
	if page_layout not in ("Auto", "Portrait", "Landscape"):
		page_layout = "Auto"

	# Legacy auto_orientation checkbox maps into page_layout when page_layout unset.
	auto = _opt("auto_orientation", "voucher_gl_auto_orientation", 1)
	if page_layout == "Auto" and not auto and filters.get("orientation") in ("Portrait", "Landscape"):
		page_layout = filters["orientation"]

	return {
		"show_logo": _opt("show_logo", "voucher_gl_show_logo", 1),
		"show_letterhead": _opt("show_letterhead", "voucher_gl_show_letterhead", 0),
		"show_amount_in_words": _opt("show_amount_in_words", "voucher_gl_show_amount_in_words", 1),
		"show_signature_block": _opt("show_signature_block", "voucher_gl_show_signature_block", 1),
		"show_attachments": _opt("append_source_attachments", "append_source_attachments", 0)
		or _opt("show_attachments", "voucher_gl_show_attachments", 0),
		"hide_empty_columns": _opt("hide_empty_columns", "voucher_gl_hide_empty_columns", 1),
		"auto_orientation": page_layout == "Auto",
		"combine_dimensions": _opt("combine_dimensions", "voucher_gl_combine_dimensions", 1),
		"page_layout": page_layout,
	}


def build_table_row_cells(
	row: dict,
	columns: list[dict],
	dimensions: list[dict],
	labels: dict[str, str],
	*,
	combine_dimensions: bool,
	currency: str,
	precision: int,
	rtl: bool = False,
	amount_scale=None,
) -> dict[str, str]:
	cells: dict[str, str] = {}

	def _fmt(value):
		return escape_text(
			format_amount(value, currency, precision, amount_scale=amount_scale)
		)

	for col in columns:
		col_id = col["id"]
		if col_id == "idx":
			cells[col_id] = escape_text(row.get("idx"))
		elif col_id in ("account_combined", "account_stacked"):
			code = escape_text(row.get("account_code") or "")
			name = escape_text(row.get("account_name") or "")
			cells[col_id] = (
				f'<div class="acct-stack"><div class="acct-code" dir="ltr">{code}</div>'
				f'<div class="acct-name" dir="auto" style="unicode-bidi:plaintext">{name}</div></div>'
			)
		elif col_id == "account_code":
			cells[col_id] = f'<span class="acct-code" dir="ltr">{escape_text(row.get("account_code"))}</span>'
		elif col_id == "account_name":
			cells[col_id] = escape_text(row.get("account_name"))
		elif col_id == "remarks":
			main = escape_text(row.get("remarks")).replace("\n", "<br>")
			compact = bool(col.get("compact_secondary"))
			standard = bool(col.get("standard_secondary"))
			secondary = ""
			if col.get("show_secondary") or compact:
				secondary = format_remarks_secondary(
					row, labels, compact=compact, standard=standard
				)
				if compact:
					dim_text = format_dimension_lines(row, dimensions, labels, rtl=rtl)
					if dim_text:
						secondary = (secondary + "\n" + dim_text) if secondary else dim_text
			if secondary:
				cells[col_id] = (
					f'<div class="remarks-main" dir="auto" style="unicode-bidi:plaintext">{main}</div>'
					f'<div class="remarks-sub" dir="auto" style="unicode-bidi:plaintext">{escape_text(secondary).replace(chr(10), "<br>")}</div>'
				)
			else:
				cells[col_id] = f'<div class="remarks-main" dir="auto" style="unicode-bidi:plaintext">{main}</div>'
		elif col_id == "debit":
			cells[col_id] = _fmt(row.get("debit"))
		elif col_id == "credit":
			cells[col_id] = _fmt(row.get("credit"))
		elif col_id == "line_amount":
			cells[col_id] = _fmt(flt(row.get("debit")) or flt(row.get("credit")))
		elif col_id == "party":
			cells[col_id] = escape_text(row.get("party_name") or row.get("party"))
		elif col_id == "dimensions_combined":
			cells[col_id] = format_dimension_html(row, dimensions, labels, rtl=rtl)
		elif col_id == "account_currency":
			cells[col_id] = escape_text(row.get("account_currency"))
		elif col_id == "debit_ac":
			cells[col_id] = escape_text(
				format_amount(
					row.get("debit_in_account_currency"),
					row.get("account_currency") or currency,
					precision,
					amount_scale=amount_scale,
				)
			)
		elif col_id == "credit_ac":
			cells[col_id] = escape_text(
				format_amount(
					row.get("credit_in_account_currency"),
					row.get("account_currency") or currency,
					precision,
					amount_scale=amount_scale,
				)
			)
		elif col_id == "party_type":
			cells[col_id] = escape_text(row.get("party_type"))
		elif col_id == "against":
			cells[col_id] = escape_text(row.get("against"))
		elif col_id == "opening":
			cells[col_id] = escape_text(row.get("is_opening"))
		elif col_id == "cancelled":
			cells[col_id] = escape_text(labels["yes"] if cint(row.get("is_cancelled")) else labels["no"])
		elif col_id == "detail_ref":
			cells[col_id] = escape_text(row.get("voucher_detail_no"))
		elif col_id.startswith("dim_"):
			fieldname = col_id[4:]
			info = (row.get("dimensions") or {}).get(fieldname) or {}
			cells[col_id] = escape_text(info.get("title") or info.get("value") or "")
		else:
			cells[col_id] = ""
	return cells


def prepare_table_rows(payload: dict, print_ctx: dict) -> list[dict]:
	columns = print_ctx["columns"]
	dimensions = payload.get("dimensions") or []
	labels = print_ctx["labels"]
	combine = print_ctx["combine_dimensions"]
	currency = print_ctx["currency"]
	precision = print_ctx["precision"]
	profile = print_ctx["column_profile"]
	rtl = bool(print_ctx.get("rtl"))
	amount_scale = print_ctx.get("amount_scale")
	hierarchical = bool(print_ctx.get("hierarchical"))
	display_nodes = payload.get("display_nodes") or []

	def _fmt(value, *, show_zero: bool = False):
		return escape_text(
			format_amount(
				value,
				currency,
				precision,
				show_zero=show_zero,
				amount_scale=amount_scale,
			)
		)

	if hierarchical and display_nodes and profile != PROFILE_FULL_AUDIT:
		out: list[dict] = []
		line_idx = 0
		for node in display_nodes:
			node_type = node.get("node_type")
			cells: dict[str, str] = {c["id"]: "" for c in columns}
			if node_type == "gl_line":
				line_idx += 1
				row = node.get("row") or {}
				cells["idx"] = str(line_idx)
				# Codes shown once on account_header — avoid repeating leaf code on every line.
				cells["account_code"] = ""
				cells["remarks"] = build_hierarchy_description_html(node, labels, rtl=rtl)
				line_amt = flt(node.get("line_amount"))
				cells["line_amount"] = _fmt(line_amt) if line_amt else ""
				cells["debit"] = _fmt(node.get("debit"))
				cells["credit"] = _fmt(node.get("credit"))
				out.append(
					{
						"idx": line_idx,
						"cells": cells,
						"remarks_plain": (node.get("description") or {}).get("main") or "",
						"node_type": node_type,
					}
				)
			elif node_type == "account_header":
				cells["account_code"] = build_hierarchy_code_html(
					node.get("account_hierarchy"),
					leaf_fallback=cstr(node.get("account_code") or ""),
				)
				cells["remarks"] = build_hierarchy_description_html(node, labels, rtl=rtl)
				out.append({"idx": "", "cells": cells, "remarks_plain": "", "node_type": node_type})
			elif node_type in ("party_header", "dimension_header"):
				cells["remarks"] = build_hierarchy_description_html(node, labels, rtl=rtl)
				out.append({"idx": "", "cells": cells, "remarks_plain": "", "node_type": node_type})
			elif node_type in ("account_subtotal", "party_subtotal", "dimension_subtotal"):
				cells["remarks"] = build_hierarchy_description_html(node, labels, rtl=rtl)
				cells["debit"] = _fmt(node.get("debit"), show_zero=True)
				cells["credit"] = _fmt(node.get("credit"), show_zero=True)
				# مبلغ جزء group rollup: dominant side total for the subgroup
				cells["line_amount"] = _fmt(
					flt(node.get("debit")) or flt(node.get("credit")), show_zero=True
				)
				out.append({"idx": "", "cells": cells, "remarks_plain": "", "node_type": node_type})
		return out

	out = []
	for row in payload.get("rows") or []:
		row_columns = [
			{
				**col,
				"show_secondary": col["id"] == "remarks" and profile != PROFILE_FULL_AUDIT,
				"compact_secondary": col["id"] == "remarks" and profile == PROFILE_COMPACT,
				"standard_secondary": col["id"] == "remarks"
				and profile in (PROFILE_STANDARD, PROFILE_MODERN),
			}
			if col["id"] == "remarks"
			else col
			for col in columns
		]
		cells = build_table_row_cells(
			row,
			row_columns,
			dimensions,
			labels,
			combine_dimensions=combine,
			currency=currency,
			precision=precision,
			rtl=rtl,
			amount_scale=amount_scale,
		)
		out.append({"idx": row.get("idx"), "cells": cells, "remarks_plain": row.get("remarks") or ""})
	return out


def resolve_company_logo_url(company: str) -> str | None:
	logo = frappe.db.get_value("Company", company, "company_logo")
	if not logo:
		return None
	if logo.startswith("/"):
		if not frappe.db.exists("File", {"file_url": logo, "is_folder": 0}):
			# file may still exist on disk; only skip obvious bad paths
			pass
		return get_url(logo)
	return None


def render_letterhead_html(letterhead_name: str | None, header: dict) -> str:
	"""Render Letter Head Jinja with voucher identity as doc — only when explicitly requested."""
	if not letterhead_name or not frappe.db.exists("Letter Head", letterhead_name):
		return ""
	if not frappe.has_permission("Letter Head", "read"):
		return ""

	doc_context = frappe._dict(
		{
			"company": header.get("company"),
			"company_name": header.get("company_name"),
			"name": header.get("voucher_no"),
			"doctype": header.get("voucher_type"),
			"posting_date": header.get("posting_date"),
			"voucher_type": header.get("voucher_type"),
			"voucher_no": header.get("voucher_no"),
		}
	)
	letter_head = frappe.get_cached_doc("Letter Head", letterhead_name)
	rendered_parts: list[str] = []
	if letter_head.content:
		try:
			rendered_parts.append(frappe.render_template(letter_head.content, {"doc": doc_context}))
		except Exception:
			# Unsafe / incompatible letterhead — omit rather than leak raw Jinja.
			return ""
	return "".join(rendered_parts)


def assert_rendered_html_safe(html: str) -> None:
	"""Fail closed if template markers leaked into final HTML."""
	if not html:
		frappe.throw(_("Print GL preview is empty."))
	if JINJA_MARKER_RE.search(html):
		frappe.throw(
			_(
				"Voucher GL Print layout is misconfigured: unresolved template markers were detected. "
				"Use built-in Standard/Modern/Compact layouts or a Voucher GL–compatible custom template."
			)
		)


def build_print_context(payload: dict, filters: dict | None = None) -> dict:
	from erpnext_extensions.iran_accounting.account_explorer.voucher_gl_hierarchy import (
		should_show_account_hierarchy,
	)

	filters = frappe._dict(filters or {})
	options = resolve_print_options(filters)
	layout = filters.get("layout") or payload.get("layout") or LAYOUT_STANDARD
	lang = resolve_print_language(filters)
	rtl = is_rtl_language(lang)
	labels = get_print_labels(lang)
	profile = resolve_column_profile(layout, filters)
	full_audit = cint(filters.get("full_audit_columns")) or layout == LAYOUT_AUDIT
	if full_audit:
		profile = PROFILE_FULL_AUDIT
	dimensions = payload.get("dimensions") or []
	combine = should_combine_dimensions(
		profile,
		dimensions,
		force_full_audit=profile == PROFILE_FULL_AUDIT,
		combine_override=None if profile == PROFILE_FULL_AUDIT else options.get("combine_dimensions"),
	)
	orientation = resolve_orientation(
		profile,
		dimensions,
		combine_dimensions=combine,
		page_layout=options.get("page_layout") or "Auto",
	)
	if filters.get("orientation") in ("Portrait", "Landscape"):
		orientation = filters["orientation"]
	currency = payload.get("summary", {}).get("currency") or payload.get("company_currency") or "INR"
	precision = cint(payload.get("precision")) or 2
	hierarchical = should_show_account_hierarchy(filters) and profile != PROFILE_FULL_AUDIT
	amount_scale = payload.get("amount_scale")
	if amount_scale is None:
		from erpnext_extensions.iran_accounting.domain.amount_scale import resolve_print_amount_scale

		scale_filters = dict(filters)
		scale_filters.setdefault("currency", currency)
		scale_filters.setdefault("language", lang)
		amount_scale = resolve_print_amount_scale(scale_filters)
	columns = build_table_columns(
		profile,
		dimensions,
		labels,
		combine_dimensions=combine,
		hierarchical=hierarchical,
	)
	columns = filter_empty_columns(
		columns,
		payload.get("rows") or [],
		dimensions,
		hide_empty=options["hide_empty_columns"] and not hierarchical,
	)
	debit_idx = next((i for i, c in enumerate(columns) if c["id"] == "debit"), len(columns) - 2)
	table_rows = prepare_table_rows(
		payload,
		{
			"columns": columns,
			"labels": labels,
			"combine_dimensions": combine,
			"currency": currency,
			"precision": precision,
			"column_profile": profile,
			"rtl": rtl,
			"amount_scale": amount_scale,
			"hierarchical": hierarchical,
		},
	)
	company = payload.get("header", {}).get("company")
	logo_url = None
	if options["show_logo"] and company:
		logo_url = resolve_company_logo_url(company)
	contact = resolve_company_contact(company) if company else {"address": "", "phone": ""}
	header = payload.get("header") or {}
	identity_rows = build_identity_rows(header, labels)
	cover_meta_rows = build_cover_meta_rows(header, labels)
	# Visible scale meta: effective scale after Auto resolution (omit Raw).
	from erpnext_extensions.iran_accounting.domain.amount_scale import (
		SCALE_RAW,
		scale_label as amount_scale_label,
	)

	effective = getattr(amount_scale, "scale", None) or SCALE_RAW
	# Resolve Auto against voucher debit for display meta.
	if cstr(effective).lower() == "auto":
		from erpnext_extensions.iran_accounting.domain.amount_scale import effective_scale

		effective = effective_scale(
			"auto",
			(payload.get("totals") or {}).get("total_debit")
			or (payload.get("summary") or {}).get("total_debit")
			or 0,
		)
	scale_lbl = amount_scale_label(effective, locale=lang)
	currency_word = localize_currency_label(currency, lang)
	amount_scale_display = ""
	if cstr(effective).lower() != SCALE_RAW:
		# FA: "میلیون ریال" · EN: stable title "Millions" (never K/M/B/T)
		if lang in ("fa", "ar") and scale_lbl:
			amount_scale_display = f"{scale_lbl} {currency_word}".strip()
		else:
			amount_scale_display = cstr(effective).replace("_", " ").title()

	layout_name = filters.get("layout") or payload.get("layout") or LAYOUT_STANDARD
	layout_label = {
		LAYOUT_STANDARD: labels.get("layout_standard") or "Standard",
		LAYOUT_MODERN: labels.get("layout_modern") or "Modern",
		LAYOUT_COMPACT: labels.get("layout_compact") or "Compact",
		LAYOUT_AUDIT: labels.get("layout_audit") or "Audit",
	}.get(layout_name, layout_name)

	return {
		"lang": lang,
		"rtl": rtl,
		"labels": labels,
		"column_profile": profile,
		"columns": columns,
		"footer_label_colspan": max(debit_idx, 1),
		"table_rows": table_rows,
		"combine_dimensions": combine,
		"orientation": orientation,
		"currency": currency,
		"currency_label": currency_word,
		"precision": precision,
		"logo_url": logo_url,
		"company_address": contact.get("address") or "",
		"company_phone": contact.get("phone") or "",
		"layout_direction": "rtl" if rtl else "ltr",
		"show_zero_amounts": cint(filters.get("show_zero_amounts")),
		"options": options,
		"identity_rows": identity_rows,
		"cover_meta_rows": cover_meta_rows,
		"voucher_description": cstr(header.get("voucher_remarks") or "").strip(),
		"amount_scale": amount_scale,
		"amount_scale_display": amount_scale_display,
		"hierarchical": hierarchical,
		"layout_label": layout_label,
	}


def localize_currency_label(currency: str, lang: str) -> str:
	"""Safe currency label for print — never broken glyphs; FA IRR → ریال."""
	code = cstr(currency or "").strip()
	if not code:
		return ""
	if lang in ("fa", "ar") and code in ("IRR", "ریال"):
		return "ریال"
	# Prefer stable ISO code over symbol glyphs that break in print fonts.
	if code in ("IRR", "USD", "EUR", "INR", "AED", "GBP"):
		return "ریال" if (lang in ("fa", "ar") and code == "IRR") else code
	# Strip common symbol-only forms
	if code in ("﷼", "ریال", "Rs", "₹", "$", "€"):
		if code in ("﷼", "ریال"):
			return "ریال" if lang in ("fa", "ar") else "IRR"
		return code
	return code


def build_identity_rows(header: dict, labels: dict[str, str]) -> list[dict[str, str]]:
	"""Right-side voucher identity — only non-empty fields."""
	candidates = [
		("voucher_number", header.get("voucher_no")),
		("posting_date", header.get("posting_date")),
		("reference_number", header.get("reference_number")),
		("voucher_type", header.get("voucher_type")),
		("status", header.get("voucher_status")),
	]
	rows: list[dict[str, str]] = []
	for key, value in candidates:
		text = cstr(value or "").strip()
		if not text:
			continue
		rows.append({"label": labels[key], "value": text})
	return rows


def build_cover_meta_rows(header: dict, labels: dict[str, str]) -> list[dict[str, str]]:
	"""Left-side secondary metadata — fiscal / book / print provenance."""
	candidates = [
		("fiscal_year", header.get("fiscal_year")),
		("finance_book", header.get("finance_book")),
		("printed_by", header.get("printed_by")),
		("print_date", header.get("print_timestamp")),
		("generated_from", header.get("print_meta_source")),
	]
	rows: list[dict[str, str]] = []
	for key, value in candidates:
		text = cstr(value or "").strip()
		if not text:
			continue
		rows.append({"label": labels[key], "value": text})
	return rows


def build_meta_rows(header: dict, labels: dict[str, str]) -> list[dict[str, str]]:
	"""Combined cover identity + meta for tests/legacy callers."""
	return build_identity_rows(header, labels) + build_cover_meta_rows(header, labels)
