# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

import csv
import io
from typing import Any

import frappe
from frappe import _
from frappe.utils import cint, now_datetime
from frappe.utils.xlsxutils import make_xlsx

from erpnext_extensions.iran_accounting.account_explorer.permissions import assert_export_allowed
from erpnext_extensions.iran_accounting.account_explorer.query_spec import (
	AccountExplorerQuerySpec_from_client,
)
from erpnext_extensions.iran_accounting.account_explorer.schemas import AccountExplorerQuerySpec

EXPORT_FORMATS = frozenset({"csv", "xlsx"})
EXPORT_AXES = frozenset({"account_level", "party", "unified_party", "dimension", "currency", "voucher"})


def _export_settings() -> dict[str, int]:
	settings = frappe.get_single("Iran Accounting Settings")
	threshold = settings.export_background_threshold
	return {
		"export_enabled": cint(settings.export_enabled),
		"export_background_threshold": cint(threshold if threshold is not None else 5000),
		"server_page_size": cint(settings.server_page_size or 200),
	}


def _run_summary_builder(spec: AccountExplorerQuerySpec) -> dict:
	axis = spec.view_axis
	if axis == "account_level":
		from erpnext_extensions.iran_accounting.account_explorer.query_builder import (
			build_account_level_summary,
		)

		return build_account_level_summary(spec)
	if axis == "party":
		from erpnext_extensions.iran_accounting.account_explorer.party_summary import build_party_summary

		return build_party_summary(spec)
	if axis == "unified_party":
		from erpnext_extensions.iran_accounting.account_explorer.unified_party_summary import (
			build_unified_party_summary,
		)

		return build_unified_party_summary(spec)
	if axis == "dimension":
		from erpnext_extensions.iran_accounting.account_explorer.dimension_summary import (
			build_dimension_summary,
		)

		return build_dimension_summary(spec)
	if axis == "currency":
		from erpnext_extensions.iran_accounting.account_explorer.currency_summary import (
			build_currency_summary,
		)

		return build_currency_summary(spec)
	if axis == "voucher":
		from erpnext_extensions.iran_accounting.account_explorer.voucher_summary import (
			build_voucher_summary,
		)

		return build_voucher_summary(spec)
	frappe.throw(_("Export is not supported for the current analysis context."))


def collect_export_rows(spec: AccountExplorerQuerySpec) -> tuple[list[dict], dict, int]:
	settings = _export_settings()
	page_size = min(settings["server_page_size"], 500)
	spec.pagination.page_size = page_size

	all_rows: list[dict] = []
	totals: dict = {}
	total_rows = 0
	page = 1

	while True:
		spec.pagination.page = page
		result = _run_summary_builder(spec)
		all_rows.extend(result.get("rows") or [])
		totals = result.get("totals") or totals
		pagination = result.get("pagination") or {}
		total_rows = cint(pagination.get("total_rows") or len(all_rows))
		if not pagination.get("has_next"):
			break
		page += 1

	return all_rows, totals, total_rows


def get_export_columns(spec: AccountExplorerQuerySpec) -> list[dict[str, str]]:
	axis = spec.view_axis
	if axis == "account_level":
		return [
			{"fieldname": "display_code", "label": _("Account Code")},
			{"fieldname": "display_title", "label": _("Account Name")},
			{"fieldname": "opening_debit", "label": _("Opening Debit")},
			{"fieldname": "opening_credit", "label": _("Opening Credit")},
			{"fieldname": "period_debit", "label": _("Period Debit")},
			{"fieldname": "period_credit", "label": _("Period Credit")},
			{"fieldname": "debit_balance", "label": _("Closing Debit")},
			{"fieldname": "credit_balance", "label": _("Closing Credit")},
		]
	if axis == "party":
		return [
			{"fieldname": "party_type", "label": _("Party Type")},
			{"fieldname": "display_code", "label": _("Party")},
			{"fieldname": "display_title", "label": _("Party Name")},
			{"fieldname": "period_debit", "label": _("Debit Turnover")},
			{"fieldname": "period_credit", "label": _("Credit Turnover")},
			{"fieldname": "debit_balance", "label": _("Debit Balance")},
			{"fieldname": "credit_balance", "label": _("Credit Balance")},
		]
	if axis == "unified_party":
		return [
			{"fieldname": "display_code", "label": _("Unified Party")},
			{"fieldname": "display_title", "label": _("Unified Name")},
			{"fieldname": "member_count", "label": _("Member Count")},
			{"fieldname": "period_debit", "label": _("Debit Turnover")},
			{"fieldname": "period_credit", "label": _("Credit Turnover")},
			{"fieldname": "debit_balance", "label": _("Debit Balance")},
			{"fieldname": "credit_balance", "label": _("Credit Balance")},
		]
	if axis == "dimension":
		return [
			{"fieldname": "dimension_type", "label": _("Dimension Type")},
			{"fieldname": "display_code", "label": _("Dimension Value")},
			{"fieldname": "display_title", "label": _("Dimension Title")},
			{"fieldname": "period_debit", "label": _("Debit Turnover")},
			{"fieldname": "period_credit", "label": _("Credit Turnover")},
			{"fieldname": "debit_balance", "label": _("Debit Balance")},
			{"fieldname": "credit_balance", "label": _("Credit Balance")},
		]
	if axis == "currency":
		return [
			{"fieldname": "currency", "label": _("Currency")},
			{"fieldname": "period_debit", "label": _("Native Debit")},
			{"fieldname": "period_credit", "label": _("Native Credit")},
			{"fieldname": "net_balance", "label": _("Native Net")},
		]
	if axis == "voucher":
		return [
			{"fieldname": "posting_date", "label": _("Posting Date")},
			{"fieldname": "voucher_type", "label": _("Voucher Type")},
			{"fieldname": "voucher_no", "label": _("Voucher No")},
			{"fieldname": "scoped_debit", "label": _("Scoped Debit")},
			{"fieldname": "scoped_credit", "label": _("Scoped Credit")},
			{"fieldname": "scoped_net", "label": _("Scoped Net")},
		]
	frappe.throw(_("Export is not supported for the current analysis context."))


def _normalize_export_rows(rows: list[dict], spec: AccountExplorerQuerySpec) -> list[dict]:
	if spec.view_axis != "dimension":
		return rows
	dimension_type = spec.dimension_scope.dimension_type
	return [{**row, "dimension_type": row.get("dimension_type") or dimension_type} for row in rows]


def rows_to_matrix(rows: list[dict], columns: list[dict[str, str]]) -> tuple[list[str], list[list[Any]]]:
	headers = [column["label"] for column in columns]
	data = [[row.get(column["fieldname"]) for column in columns] for row in rows]
	return headers, data


def build_csv_content(rows: list[dict], columns: list[dict[str, str]]) -> str:
	headers, data = rows_to_matrix(rows, columns)
	buffer = io.StringIO()
	writer = csv.writer(buffer)
	writer.writerow(headers)
	writer.writerows(data)
	return buffer.getvalue()


def build_xlsx_content(rows: list[dict], columns: list[dict[str, str]]) -> bytes:
	headers, data = rows_to_matrix(rows, columns)
	xlsx_file = make_xlsx([headers, *data], "Account Explorer")
	return xlsx_file.getvalue()


def _export_filename(spec: AccountExplorerQuerySpec, file_format: str) -> str:
	timestamp = now_datetime().strftime("%Y%m%d_%H%M%S")
	return f"account_explorer_{spec.view_axis}_{timestamp}.{file_format}"


def _save_export_file(content: bytes | str, filename: str, file_format: str) -> str:
	if file_format == "xlsx":
		from frappe.utils.file_manager import save_file

		file_doc = save_file(filename, content, None, None, is_private=1)
		return file_doc.file_url

	file_doc = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": filename,
			"is_private": 1,
			"content": content,
		}
	)
	file_doc.save(ignore_permissions=True)
	return file_doc.file_url


def _send_export_ready_email(user: str, file_url: str, filename: str) -> None:
	frappe.sendmail(
		recipients=[user],
		subject=_("Account Explorer export is ready"),
		message=_("Your export {0} is ready: {1}").format(filename, file_url),
		now=True,
	)


def _prepare_export_payload(payload: Any) -> AccountExplorerQuerySpec:
	assert_export_allowed()
	spec = AccountExplorerQuerySpec_from_client(payload, require_dates=True)
	if spec.detail_mode != "summary":
		frappe.throw(_("Export is only supported for summary view."))
	if spec.view_axis not in EXPORT_AXES:
		frappe.throw(_("Export is not supported for the current analysis axis."))
	return spec


def _probe_export_size(spec: AccountExplorerQuerySpec) -> int:
	settings = _export_settings()
	page_size = min(settings["server_page_size"], 500)
	spec.pagination.page_size = page_size
	spec.pagination.page = 1
	result = _run_summary_builder(spec)
	return cint((result.get("pagination") or {}).get("total_rows") or 0)


def _trigger_download(content: bytes | str, filename: str) -> None:
	frappe.local.response.filename = filename
	frappe.local.response.filecontent = content
	frappe.local.response.type = "download"


def export_account_explorer(payload: Any, file_format: str = "csv", *, force_sync: bool = False) -> dict:
	file_format = (file_format or "csv").lower()
	if file_format not in EXPORT_FORMATS:
		frappe.throw(_("Unsupported export format."))

	spec = _prepare_export_payload(payload)
	settings = _export_settings()
	total_rows = _probe_export_size(spec)

	if not force_sync and total_rows > settings["export_background_threshold"]:
		frappe.enqueue(
			"erpnext_extensions.iran_accounting.account_explorer.export.run_account_explorer_export_job",
			queue="long",
			payload=payload,
			file_format=file_format,
			user=frappe.session.user,
		)
		return {
			"queued": 1,
			"total_rows": total_rows,
			"message": _("Export queued in background because the dataset exceeds {0} rows.").format(
				settings["export_background_threshold"]
			),
		}

	rows, totals, total_rows = collect_export_rows(spec)
	columns = get_export_columns(spec)
	rows = _normalize_export_rows(rows, spec)
	filename = _export_filename(spec, file_format)

	if file_format == "csv":
		_trigger_download(build_csv_content(rows, columns), filename)
	else:
		_trigger_download(build_xlsx_content(rows, columns), filename)

	return {
		"queued": 0,
		"total_rows": total_rows,
		"filename": filename,
		"totals": totals,
	}


def run_account_explorer_export_job(payload: Any, file_format: str, user: str) -> None:
	frappe.set_user(user)
	spec = _prepare_export_payload(payload)
	rows, _, _total_rows = collect_export_rows(spec)
	columns = get_export_columns(spec)
	rows = _normalize_export_rows(rows, spec)
	filename = _export_filename(spec, file_format)

	if file_format == "csv":
		content = build_csv_content(rows, columns)
	else:
		content = build_xlsx_content(rows, columns)

	file_url = _save_export_file(content, filename, file_format)
	_send_export_ready_email(user, file_url, filename)
