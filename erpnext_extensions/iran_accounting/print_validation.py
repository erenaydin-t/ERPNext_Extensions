# Copyright (c) 2026, ERPNext Extensions contributors

from __future__ import annotations

import frappe

from erpnext_extensions.iran_accounting.diagnostics import check_print_output as _check_print_output
from erpnext_extensions.iran_accounting.validation import (
	check_print_html_no_irr_monetary_decimals,
	find_irr_monetary_decimal_snippets,
)


def assert_irr_print_has_no_decimals(voucher_no: str, doctype: str = "Stock Entry") -> dict:
	return _check_print_output(voucher_no, doctype=doctype)


def check_voucher_print(doctype: str, voucher_no: str) -> dict:
	html = frappe.get_print(doctype, voucher_no)
	result = check_print_html_no_irr_monetary_decimals(html)
	result["voucher_no"] = voucher_no
	result["doctype"] = doctype
	return result
