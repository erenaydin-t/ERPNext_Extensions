# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

import frappe


def after_migrate() -> None:
	provision_facility_accounting_dimension()


def provision_facility_accounting_dimension() -> None:
	if not frappe.db.exists("DocType", "Accounting Dimension"):
		return
	if not frappe.db.exists("DocType", "Facility"):
		return
	if frappe.db.exists("Accounting Dimension", {"document_type": "Facility", "disabled": 0}):
		return
	doc = frappe.get_doc(
		{
			"doctype": "Accounting Dimension",
			"label": "Facility",
			"document_type": "Facility",
		}
	)
	doc.insert(ignore_permissions=True)
	frappe.db.commit()
