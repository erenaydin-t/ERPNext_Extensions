# Copyright (c) 2026, Farbod Siyahpoosh and contributors
"""Request-local caches for Account Explorer hot paths (v4.6.0)."""

from __future__ import annotations

import frappe
from frappe.utils.caching import request_cache


@request_cache
def get_iran_accounting_settings():
	return frappe.get_single("Iran Accounting Settings")


@request_cache
def get_selling_customer_naming_mode() -> str:
	return frappe.get_single_value("Selling Settings", "cust_master_name") or "Customer Name"


@request_cache
def get_buying_supplier_naming_mode() -> str:
	return frappe.get_single_value("Buying Settings", "supp_master_name") or "Supplier Name"
