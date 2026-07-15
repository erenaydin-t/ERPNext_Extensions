# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint

from erpnext_extensions.iran_accounting.account_explorer.permissions import assert_gl_navigation_allowed
from erpnext_extensions.iran_accounting.account_explorer.query_spec import AccountExplorerQuerySpec_from_client
from erpnext_extensions.iran_accounting.account_explorer.schemas import AccountExplorerQuerySpec
from erpnext_extensions.iran_accounting.account_explorer.voucher_gl_print import (
	DEFAULT_VOUCHER_GL_PRINT_FORMAT,
	VOUCHER_GL_PRINT_REPORT,
)


def resolve_voucher_navigation(payload) -> dict:
	spec = AccountExplorerQuerySpec_from_client(payload, require_dates=True)
	voucher_type = spec.voucher_scope.voucher_type
	voucher_no = spec.voucher_scope.voucher_no
	if not voucher_type or not voucher_no:
		frappe.throw(_("Voucher type and voucher number are required."))

	navigation_allowed = _navigation_allowed()
	messages: list[str] = []
	can_open_gl_list = navigation_allowed and frappe.has_permission("GL Entry", "read")
	can_open_source = False
	source_route = None

	if not navigation_allowed:
		messages.append(_("GL Entry navigation is disabled in Iran Accounting Settings."))

	gl_list_route = [
		"List",
		"GL Entry",
		{
			"company": spec.company,
			"voucher_type": voucher_type,
			"voucher_no": voucher_no,
			"from_date": str(spec.from_date),
			"to_date": str(spec.to_date),
		},
	]

	if navigation_allowed and frappe.db.exists(voucher_type, voucher_no):
		if frappe.has_permission(voucher_type, "read", voucher_no):
			can_open_source = True
			source_route = ["Form", voucher_type, voucher_no]
		else:
			messages.append(_("You do not have permission to open {0} {1}.").format(voucher_type, voucher_no))
	elif navigation_allowed:
		messages.append(_("Source document {0} {1} was not found.").format(voucher_type, voucher_no))

	settings = frappe.get_cached_doc("Iran Accounting Settings")
	show_print_voucher = cint(settings.get("show_print_voucher", 1))
	show_print_gl = cint(settings.get("show_print_gl", 1))
	source_print_format = settings.account_explorer_voucher_print_format
	gl_print_format = settings.get("voucher_gl_print_format") or DEFAULT_VOUCHER_GL_PRINT_FORMAT

	can_print = bool(show_print_voucher and source_print_format and can_open_source)
	print_route = None
	if can_print:
		print_route = {
			"doctype": voucher_type,
			"name": voucher_no,
			"format": source_print_format,
		}

	can_print_gl = bool(
		show_print_gl
		and gl_print_format
		and frappe.has_permission("GL Entry", "read")
		and cint(settings.account_explorer_enabled)
	)
	print_gl_route = None
	if can_print_gl:
		layout = settings.get("voucher_gl_layout") or "Standard"
		route_filters = {
			"company": spec.company,
			"voucher_type": voucher_type,
			"voucher_no": voucher_no,
			"include_opening_entries": cint(spec.include_opening_entries),
			"include_cancelled_entries": cint(spec.include_cancelled_entries),
			"finance_book": spec.finance_book,
			"layout": layout,
		}
		from urllib.parse import urlencode

		query = urlencode({k: v for k, v in route_filters.items() if v not in (None, "")})
		print_gl_route = {
			"report": VOUCHER_GL_PRINT_REPORT,
			"format": gl_print_format,
			"layout": layout,
			"filters": route_filters,
			# Stable Desk report URL — no HTML / GL rows in query string.
			"url_path": f"/app/query-report/{VOUCHER_GL_PRINT_REPORT}?{query}",
		}

	return {
		"voucher_type": voucher_type,
		"voucher_no": voucher_no,
		"doctype": voucher_type,
		"docname": voucher_no,
		"can_open_source": can_open_source,
		"can_open_gl_list": can_open_gl_list,
		"can_print": can_print,
		"can_print_gl": can_print_gl,
		"print_format": source_print_format,
		"voucher_gl_print_format": gl_print_format if can_print_gl else None,
		"show_print_voucher": show_print_voucher,
		"show_print_gl": show_print_gl,
		"source_route": source_route,
		"gl_list_route": gl_list_route if can_open_gl_list else None,
		"print_route": print_route,
		"print_gl_route": print_gl_route,
		"messages": messages,
	}


def _navigation_allowed() -> bool:
	try:
		assert_gl_navigation_allowed()
	except frappe.ValidationError:
		return False
	return True


def build_navigation_from_spec(spec: AccountExplorerQuerySpec) -> dict:
	return resolve_voucher_navigation(_payload_from_spec(spec))


def _payload_from_spec(spec: AccountExplorerQuerySpec) -> str:
	import json

	return json.dumps(
		{
			"document_scope": {
				"company": spec.company,
				"from_date": str(spec.from_date),
				"to_date": str(spec.to_date),
				"fiscal_year": spec.fiscal_year,
			},
			"analysis_context": {
				"voucher_scope": {
					"voucher_type": spec.voucher_scope.voucher_type,
					"voucher_no": spec.voucher_scope.voucher_no,
				}
			},
		}
	)
