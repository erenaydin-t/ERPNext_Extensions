"""Payment Entry hooks for Petty Management funding linkage."""

from __future__ import annotations

import frappe

from erpnext_extensions.petty_management.services.request_service import (
	derive_payment_status,
	sync_request_status_from_workflow,
)


def on_payment_entry_submit(doc, method=None):
	"""Keep PM Request payment_status / status aligned when PE is submitted outside PM Request."""
	from erpnext_extensions.petty_management import petty_audit

	names = frappe.get_all("PM Request", filters={"payment_entry": doc.name}, pluck="name")
	for name in names:
		pm = frappe.get_doc("PM Request", name)
		derive_payment_status(pm)
		sync_request_status_from_workflow(pm)
		frappe.db.set_value(
			"PM Request",
			name,
			{"payment_status": pm.payment_status, "status": pm.status},
			update_modified=False,
		)
	for name in names:
		try:
			pm_row = frappe.db.get_value("PM Request", name, ["holder", "employee", "company"], as_dict=True)
			petty_audit.log_event(
				"pm_payment_entry_submitted",
				pm_request=name,
				payment_entry=doc.name,
				holder=pm_row.get("holder") if pm_row else None,
				employee=pm_row.get("employee") if pm_row else None,
				company=pm_row.get("company") if pm_row else None,
			)
		except Exception:
			pass


def on_payment_entry_cancel(doc, method=None):
	"""Rollback funding fields when Payment Entry is cancelled."""
	from erpnext_extensions.petty_management import petty_audit

	names = frappe.get_all("PM Request", filters={"payment_entry": doc.name}, pluck="name")
	for name in names:
		frappe.db.set_value("PM Request", name, {"payment_entry": None}, update_modified=False)
		pm = frappe.get_doc("PM Request", name)
		derive_payment_status(pm)
		sync_request_status_from_workflow(pm)
		frappe.db.set_value(
			"PM Request",
			name,
			{"payment_status": pm.payment_status, "status": pm.status},
			update_modified=False,
		)
	for name in names:
		try:
			pm_row = frappe.db.get_value("PM Request", name, ["holder", "employee", "company"], as_dict=True)
			petty_audit.log_event(
				"pm_payment_entry_cancelled",
				pm_request=name,
				payment_entry=doc.name,
				holder=pm_row.get("holder") if pm_row else None,
				employee=pm_row.get("employee") if pm_row else None,
				company=pm_row.get("company") if pm_row else None,
			)
		except Exception:
			pass
