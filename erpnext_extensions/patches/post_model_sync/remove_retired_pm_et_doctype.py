from __future__ import annotations

import frappe

DOCTYPE_NAME = "PM Expense Type"


def execute():
	"""Drop retired petty cash expense-category DocType from DB if present (idempotent)."""
	if not frappe.db.exists("DocType", DOCTYPE_NAME):
		return
	try:
		frappe.delete_doc("DocType", DOCTYPE_NAME, force=True, ignore_missing=True)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "petty_mgmt_dt_cleanup")
	frappe.db.commit()
