# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

import frappe

from erpnext_extensions.asset_usage_depreciation.custom_fields import ensure_custom_fields
from erpnext_extensions.asset_usage_depreciation.constants import MODULE


def _ensure_module_def():
	if frappe.db.exists("Module Def", MODULE):
		return
	doc = frappe.get_doc(
		{
			"doctype": "Module Def",
			"module_name": MODULE,
			"app_name": "erpnext_extensions",
		}
	)
	doc.insert(ignore_permissions=True)


def after_migrate():
	_ensure_module_def()
	ensure_custom_fields()
