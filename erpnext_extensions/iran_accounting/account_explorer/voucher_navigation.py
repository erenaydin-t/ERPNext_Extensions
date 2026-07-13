# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

import frappe
from frappe import _

from erpnext_extensions.iran_accounting.account_explorer.permissions import assert_gl_navigation_allowed
from erpnext_extensions.iran_accounting.account_explorer.query_spec import AccountExplorerQuerySpec_from_client
from erpnext_extensions.iran_accounting.account_explorer.schemas import AccountExplorerQuerySpec


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

	return {
		"voucher_type": voucher_type,
		"voucher_no": voucher_no,
		"doctype": voucher_type,
		"docname": voucher_no,
		"can_open_source": can_open_source,
		"can_open_gl_list": can_open_gl_list,
		"source_route": source_route,
		"gl_list_route": gl_list_route if can_open_gl_list else None,
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
