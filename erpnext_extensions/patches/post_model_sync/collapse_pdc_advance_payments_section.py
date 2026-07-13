from __future__ import annotations

import frappe


def _set(dt: str, fieldname: str, **values) -> None:
	name = frappe.db.get_value("Custom Field", {"dt": dt, "fieldname": fieldname}, "name")
	if not name:
		return
	# Frappe versions differ: `tabCustom Field` may not have a `collapsed` column.
	if "collapsed" in values and not frappe.db.has_column("Custom Field", "collapsed"):
		values.pop("collapsed")
	for k, v in values.items():
		frappe.db.set_value("Custom Field", name, k, v, update_modified=False)


def execute():
	# UX polish: match native Advances section behavior (collapsible + collapsed by default).
	for dt in ("Purchase Invoice", "Sales Invoice"):
		_set(dt, "pdc_advance_payments_section", collapsible=1, collapsed=1)
