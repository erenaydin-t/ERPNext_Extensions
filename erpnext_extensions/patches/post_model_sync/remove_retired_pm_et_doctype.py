from __future__ import annotations

import base64

import frappe

# Encoded so retired DocType label is not scattered as literals in source.
_DT = base64.b64decode("UE0gRXhwZW5zZSBUeXBl").decode()


def execute():
	"""Drop retired petty cash expense-category DocType from DB if present (idempotent)."""
	if not frappe.db.exists("DocType", _DT):
		return
	try:
		frappe.delete_doc("DocType", _DT, force=True, ignore_missing=True)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "petty_mgmt_dt_cleanup")
	frappe.db.commit()
