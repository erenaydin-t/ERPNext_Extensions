# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

from erpnext_extensions.iran_accounting.account_explorer.voucher_gl_layout import build_print_context
from erpnext_extensions.iran_accounting.account_explorer.voucher_gl_print import (
	build_voucher_gl_print,
	flatten_rows_for_report,
	get_report_columns,
)
from erpnext_extensions.iran_accounting.account_explorer.voucher_gl_renderer import enrich_print_payload


def execute(filters=None):
	payload = enrich_print_payload(build_voucher_gl_print(filters), filters)
	print_ctx = build_print_context(payload, filters)
	columns = get_report_columns(payload.get("dimensions") or [])
	data = flatten_rows_for_report(payload)
	message = {
		"header": payload["header"],
		"totals": payload["totals"],
		"summary": payload.get("summary"),
		"orientation": print_ctx["orientation"],
		"layout_direction": print_ctx["layout_direction"],
		"print_format": payload["print_format"],
		"dimensions": payload["dimensions"],
		"column_profile": print_ctx["column_profile"],
	}
	return columns, data, message
