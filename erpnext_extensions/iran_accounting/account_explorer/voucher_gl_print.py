# Copyright (c) 2026, Farbod Siyahpoosh and contributors
"""Enterprise Voucher GL Printing — Script Report data + one-click print HTML.

Print GL prints every GL Entry row belonging to one voucher (not the source
document, not a summary, not Excel export).
"""

from __future__ import annotations

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import cint, cstr, flt, format_datetime, now_datetime

from erpnext_extensions.iran_accounting.account_explorer.dimension_discovery import (
	get_discovered_dimensions,
)
from erpnext_extensions.iran_accounting.account_explorer.permissions import (
	assert_accounts_role,
	assert_company_allowed,
	assert_feature_enabled,
)
from erpnext_extensions.iran_accounting.account_explorer.voucher_gl import (
	_dimension_title_maps,
)
from erpnext_extensions.iran_accounting.account_explorer.voucher_summary import _party_name

VOUCHER_GL_PRINT_REPORT = "Voucher GL Print"
DEFAULT_VOUCHER_GL_PRINT_FORMAT = "Voucher GL Print Standard"
LANDSCAPE_DIMENSION_THRESHOLD = 4


def build_voucher_gl_print(filters) -> dict:
	"""Build header, rows, totals, and layout hints for one voucher.

	SQL budget:
	- 1 parameterized GL Entry select for all lines (GROUP BY account not used —
	  every row must print).
	- Batch title resolution for accounts / parties / dimensions (no per-row
	  queries). Header fields are derived from the same GL result set.
	"""
	filters = frappe._dict(filters or {})
	company = filters.get("company")
	voucher_type = filters.get("voucher_type")
	voucher_no = filters.get("voucher_no")
	if not company:
		frappe.throw(_("Company is required."))
	if not voucher_type or not voucher_no:
		frappe.throw(_("Voucher Type and Voucher Number are required."))

	assert_feature_enabled()
	assert_accounts_role()
	assert_company_allowed(company)
	if not frappe.has_permission("GL Entry", "read"):
		frappe.throw(_("Not permitted to read GL Entry."), frappe.PermissionError)
	if frappe.db.exists(voucher_type, voucher_no) and not frappe.has_permission(
		voucher_type, "read", voucher_no
	):
		frappe.throw(
			_("Not permitted to read {0} {1}.").format(voucher_type, voucher_no),
			frappe.PermissionError,
		)

	include_cancelled = cint(filters.get("include_cancelled_entries"))
	include_opening = cint(filters.get("include_opening_entries", 1))
	finance_book = filters.get("finance_book")

	dimensions = get_discovered_dimensions()
	raw_rows = _fetch_gl_rows(
		company=company,
		voucher_type=voucher_type,
		voucher_no=voucher_no,
		dimensions=dimensions,
		include_cancelled=include_cancelled,
		include_opening=include_opening,
		finance_book=finance_book,
	)
	if not raw_rows:
		frappe.throw(
			_("No GL Entry rows found for {0} {1}.").format(voucher_type, voucher_no)
		)

	account_meta = _account_meta_map({row.account for row in raw_rows if row.account})
	dimension_titles = _dimension_title_maps(dimensions, raw_rows)
	party_names = _party_name_map(raw_rows)

	rows: list[dict] = []
	total_debit = 0.0
	total_credit = 0.0
	for index, row in enumerate(raw_rows, start=1):
		debit = flt(row.debit)
		credit = flt(row.credit)
		total_debit += debit
		total_credit += credit
		dim_values = {}
		for dimension in dimensions:
			fieldname = dimension["fieldname"]
			value = row.get(fieldname) or ""
			title = dimension_titles.get(fieldname, {}).get(value, "") if value else ""
			dim_values[fieldname] = {
				"value": value,
				"title": title or value,
				"label": dimension["label"],
			}
		party_type = row.party_type or ""
		party = row.party or ""
		meta = account_meta.get(row.account) or {}
		rows.append(
			{
				"idx": index,
				"account": row.account,
				"account_code": meta.get("account_number") or row.account,
				"account_name": meta.get("account_name") or row.account,
				"party_type": party_type,
				"party": party,
				"party_name": party_names.get((party_type, party), "") or party,
				"debit": debit,
				"credit": credit,
				"account_currency": row.account_currency or "",
				"debit_in_account_currency": flt(row.debit_in_account_currency),
				"credit_in_account_currency": flt(row.credit_in_account_currency),
				"cost_center": row.get("cost_center") or "",
				"project": row.get("project") or "",
				"dimensions": dim_values,
				"against": row.against or "",
				"remarks": row.remarks or "",
				"finance_book": row.finance_book or "",
				"is_opening": row.is_opening or "No",
				"is_cancelled": cint(row.is_cancelled),
				"voucher_detail_no": row.voucher_detail_no or "",
				"posting_date": str(row.posting_date) if row.posting_date else "",
			}
		)

	difference = flt(total_debit - total_credit, 9)
	header = _build_header(
		company=company,
		voucher_type=voucher_type,
		voucher_no=voucher_no,
		raw_rows=raw_rows,
		party_names=party_names,
		filters=filters,
	)
	print_format = (
		filters.get("print_format")
		or frappe.get_single_value("Iran Accounting Settings", "voucher_gl_print_format")
		or DEFAULT_VOUCHER_GL_PRINT_FORMAT
	)

	return {
		"report_name": VOUCHER_GL_PRINT_REPORT,
		"print_format": print_format,
		"dimensions": dimensions,
		"header": header,
		"rows": rows,
		"totals": {
			"total_debit": total_debit,
			"total_credit": total_credit,
			"difference": difference,
			"is_balanced": abs(difference) < 1e-9,
		},
	}


def get_report_columns(dimensions: list[dict] | None = None) -> list[dict]:
	dimensions = dimensions if dimensions is not None else get_discovered_dimensions()
	columns = [
		{"label": _(""), "fieldname": "idx", "fieldtype": "Int", "width": 40},
		{"label": _("Account Code"), "fieldname": "account_code", "fieldtype": "Data", "width": 110},
		{"label": _("Account Name"), "fieldname": "account_name", "fieldtype": "Data", "width": 180},
		{"label": _("Remarks"), "fieldname": "remarks", "fieldtype": "Data", "width": 160},
		{"label": _("Debit"), "fieldname": "debit", "fieldtype": "Currency", "width": 120},
		{"label": _("Credit"), "fieldname": "credit", "fieldtype": "Currency", "width": 120},
		{"label": _("Account Currency"), "fieldname": "account_currency", "fieldtype": "Data", "width": 90},
		{
			"label": _("Debit (Account Currency)"),
			"fieldname": "debit_in_account_currency",
			"fieldtype": "Currency",
			"width": 130,
		},
		{
			"label": _("Credit (Account Currency)"),
			"fieldname": "credit_in_account_currency",
			"fieldtype": "Currency",
			"width": 130,
		},
		{"label": _("Party Type"), "fieldname": "party_type", "fieldtype": "Data", "width": 100},
		{"label": _("Party"), "fieldname": "party", "fieldtype": "Data", "width": 140},
		{"label": _("Against"), "fieldname": "against", "fieldtype": "Data", "width": 140},
		{"label": _("Cost Center"), "fieldname": "cost_center", "fieldtype": "Data", "width": 120},
		{"label": _("Project"), "fieldname": "project", "fieldtype": "Data", "width": 120},
	]
	seen_dims = {"cost_center", "project"}
	for dimension in dimensions:
		if dimension["fieldname"] in seen_dims:
			continue
		columns.append(
			{
				"label": _(dimension["label"]),
				"fieldname": f"dim_{dimension['fieldname']}",
				"fieldtype": "Data",
				"width": 120,
			}
		)
	columns.extend(
		[
			{"label": _("Opening"), "fieldname": "is_opening", "fieldtype": "Data", "width": 70},
			{"label": _("Cancelled"), "fieldname": "is_cancelled", "fieldtype": "Check", "width": 80},
			{
				"label": _("Voucher Detail Reference"),
				"fieldname": "voucher_detail_no",
				"fieldtype": "Data",
				"width": 140,
			},
		]
	)
	return columns


def flatten_rows_for_report(payload: dict) -> list[dict]:
	flat: list[dict] = []
	for row in payload.get("rows") or []:
		item = dict(row)
		for fieldname, info in (row.get("dimensions") or {}).items():
			item[f"dim_{fieldname}"] = info.get("title") or info.get("value") or ""
		flat.append(item)
	return flat


def render_voucher_gl_print_html(filters) -> str:
	"""One-click Print GL HTML via the reusable Voucher GL Renderer."""
	from erpnext_extensions.iran_accounting.account_explorer.voucher_gl_renderer import (
		render_voucher_package,
	)

	return render_voucher_package(filters)


def _fetch_gl_rows(
	*,
	company: str,
	voucher_type: str,
	voucher_no: str,
	dimensions: list[dict],
	include_cancelled: int,
	include_opening: int,
	finance_book: str | None,
) -> list[dict]:
	gle = frappe.qb.DocType("GL Entry")
	select_fields = [
		gle.name,
		gle.posting_date,
		gle.account,
		gle.party_type,
		gle.party,
		gle.debit,
		gle.credit,
		gle.account_currency,
		gle.debit_in_account_currency,
		gle.credit_in_account_currency,
		gle.against,
		gle.remarks,
		gle.finance_book,
		gle.is_opening,
		gle.is_cancelled,
		gle.voucher_detail_no,
		gle.cost_center,
		gle.project,
		gle.company,
		gle.fiscal_year,
		gle.voucher_type,
		gle.voucher_no,
		gle.owner,
		gle.creation,
	]
	seen = {"cost_center", "project"}
	for dimension in dimensions:
		fieldname = dimension["fieldname"]
		if fieldname in seen:
			continue
		select_fields.append(gle[fieldname])
		seen.add(fieldname)

	query = frappe.qb.from_(gle).select(*select_fields)
	query = query.where(gle.company == company)
	query = query.where(gle.voucher_type == voucher_type)
	query = query.where(gle.voucher_no == voucher_no)
	if not include_cancelled:
		query = query.where(gle.is_cancelled == 0)
	if not include_opening:
		query = query.where(gle.is_opening == "No")
	if finance_book:
		query = query.where((gle.finance_book == finance_book) | (gle.finance_book.isnull()) | (gle.finance_book == ""))
	query = query.orderby(gle.creation).orderby(gle.name)
	return query.run(as_dict=True)


def _party_name_map(raw_rows: list[dict]) -> dict[tuple[str, str], str]:
	grouped: dict[str, set[str]] = defaultdict(set)
	for row in raw_rows:
		if row.party_type and row.party:
			grouped[row.party_type].add(row.party)
	result: dict[tuple[str, str], str] = {}
	for party_type, parties in grouped.items():
		for party in parties:
			result[(party_type, party)] = _party_name(party_type, party) or party
	return result


def _build_header(*, company, voucher_type, voucher_no, raw_rows, party_names, filters) -> dict:
	first = raw_rows[0]
	party_type = first.party_type or ""
	party = first.party or ""
	# Prefer first non-blank party on the voucher
	for row in raw_rows:
		if row.party_type and row.party:
			party_type = row.party_type
			party = row.party
			break

	fiscal_year = first.fiscal_year
	if not fiscal_year:
		fiscal_year = frappe.db.get_value(
			"Fiscal Year",
			{"year_start_date": ("<=", first.posting_date), "year_end_date": (">=", first.posting_date)},
			"name",
		)

	prepared_by = first.owner
	prepared_by_name = frappe.db.get_value("User", prepared_by, "full_name") or prepared_by
	printed_by = frappe.session.user
	printed_by_name = frappe.db.get_value("User", printed_by, "full_name") or printed_by
	print_timestamp = format_datetime(now_datetime())

	source_exists = bool(frappe.db.exists(voucher_type, voucher_no))
	posting_time = ""
	voucher_status = _("GL Entry")
	voucher_remarks = ""
	reference_number = ""
	if source_exists:
		meta = frappe.get_meta(voucher_type)
		fields = []
		for candidate in (
			"posting_time",
			"status",
			"workflow_state",
			"docstatus",
			"user_remark",
			"remark",
			"remarks",
			"cheque_no",
			"bill_no",
			"cheque_number",
		):
			if meta.has_field(candidate) or candidate == "docstatus":
				fields.append(candidate)
		# Always fetch docstatus
		if "docstatus" not in fields:
			fields.append("docstatus")
		values = frappe.db.get_value(voucher_type, voucher_no, fields, as_dict=True) or {}
		if meta.has_field("posting_time"):
			posting_time = cstr(values.get("posting_time") or "")
		if meta.has_field("status") and values.get("status"):
			voucher_status = cstr(values.get("status"))
		elif meta.has_field("workflow_state") and values.get("workflow_state"):
			voucher_status = cstr(values.get("workflow_state"))
		else:
			ds = cint(values.get("docstatus"))
			voucher_status = {0: _("Draft"), 1: _("Submitted"), 2: _("Cancelled")}.get(ds, _("Unknown"))
		for remark_field in ("user_remark", "remark", "remarks"):
			if values.get(remark_field):
				voucher_remarks = cstr(values.get(remark_field))
				break
		for ref_field in ("cheque_no", "bill_no", "cheque_number"):
			if values.get(ref_field):
				reference_number = cstr(values.get(ref_field))
				break
		if cint(values.get("docstatus")) == 2:
			voucher_status = _("Cancelled")
	currencies = sorted({row.account_currency for row in raw_rows if row.account_currency})

	return {
		"company": company,
		"company_name": frappe.get_cached_value("Company", company, "company_name") or company,
		"title": _("Accounting Voucher"),
		"voucher_type": voucher_type,
		"voucher_no": voucher_no,
		"voucher_status": voucher_status,
		"posting_date": str(first.posting_date) if first.posting_date else "",
		"posting_time": posting_time,
		"fiscal_year": fiscal_year or "",
		"finance_book": filters.get("finance_book") or first.finance_book or "",
		"source_document": f"{voucher_type} {voucher_no}" if source_exists else "",
		"print_meta_source": _("Account Explorer"),
		"voucher_remarks": voucher_remarks,
		"reference_number": reference_number,
		"party_type": party_type,
		"party": party,
		"party_name": party_names.get((party_type, party), "") or party,
		"currency": ", ".join(currencies),
		"prepared_by": prepared_by_name,
		"printed_by": printed_by_name,
		"print_timestamp": print_timestamp,
		"page_label": _("Page"),
	}


def _account_meta_map(accounts: set[str]) -> dict[str, dict]:
	if not accounts:
		return {}
	return {
		row.name: {
			"account_name": row.account_name or row.name,
			"account_number": row.account_number or "",
		}
		for row in frappe.get_all(
			"Account",
			filters={"name": ["in", list(accounts)]},
			fields=["name", "account_name", "account_number"],
		)
	}


def _fmt_amount(value, precision=2) -> str:
	"""Full accounting amount — never abbreviated to K/M/B."""
	return frappe.format_value(flt(value), {"fieldtype": "Currency", "precision": precision})


def _optional_qr_data_url(header: dict) -> str | None:
	"""Optional QR payload for voucher identity. Soft-fails if libs unavailable."""
	try:
		import base64
		from io import BytesIO

		import qrcode
	except Exception:
		return None
	try:
		payload = "|".join(
			[
				cstr(header.get("company")),
				cstr(header.get("voucher_type")),
				cstr(header.get("voucher_no")),
				cstr(header.get("posting_date")),
			]
		)
		img = qrcode.make(payload)
		buf = BytesIO()
		img.save(buf, format="PNG")
		return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
	except Exception:
		return None

