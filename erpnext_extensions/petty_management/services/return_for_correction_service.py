# Copyright (c) 2026, ERPNext Extensions contributors
"""v4.7.2 — PM Return for Correction post-hook (same doc → Draft, no Cancel/Amend)."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint

PM_RETURN_FOR_CORRECTION = "PM Return for Correction"

REQUEST_STAMP_FIELDS = ("manager_approver", "ceo_approver", "finance_approver")
CLEARANCE_STAMP_FIELDS = ("manager_approver", "finance_approver")


def clear_approver_stamps(doc: Document) -> None:
	"""Clear named approver stamps after return to Draft."""
	fields = REQUEST_STAMP_FIELDS if doc.doctype == "PM Request" else CLEARANCE_STAMP_FIELDS
	values = {f: None for f in fields if hasattr(doc, f) or frappe.get_meta(doc.doctype).has_field(f)}
	for field in values:
		setattr(doc, field, None)
	if getattr(doc, "name", None) and values:
		frappe.db.set_value(doc.doctype, doc.name, values, update_modified=False)


def close_todos_for_doc(doctype: str, name: str) -> int:
	"""Close open ToDos linked to this document."""
	if not name:
		return 0
	open_todos = frappe.get_all(
		"ToDo",
		filters={"reference_type": doctype, "reference_name": name, "status": "Open"},
		pluck="name",
	)
	for todo_name in open_todos:
		frappe.db.set_value("ToDo", todo_name, "status", "Closed", update_modified=False)
	return len(open_todos)


def assign_requester(doc: Document) -> None:
	"""Assign the document owner (requester) after return for correction."""
	owner = (getattr(doc, "owner", None) or "").strip()
	if not owner or owner in ("Administrator", "Guest"):
		return
	if not frappe.db.exists("User", owner):
		return
	try:
		from frappe.desk.form import assign_to

		assign_to.add(
			{
				"assign_to": [owner],
				"doctype": doc.doctype,
				"name": doc.name,
				"description": _("Returned for correction: {0}").format(doc.name),
				"notify": 0,
			}
		)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "PM Return for Correction assign_requester")


def add_return_timeline_comment(doc: Document, *, from_state: str | None = None) -> None:
	msg = _("Returned for correction")
	if from_state:
		msg = _("Returned for correction from {0}").format(from_state)
	doc.add_comment("Info", msg)


def handle_return_for_correction(doc: Document, *, from_state: str | None = None) -> Document:
	"""After successful Return transition: clear stamps, close ToDos, assign owner, sync Draft."""
	if doc.doctype not in ("PM Request", "PM Clearance"):
		return doc
	doc.reload()
	clear_approver_stamps(doc)
	close_todos_for_doc(doc.doctype, doc.name)
	assign_requester(doc)
	add_return_timeline_comment(doc, from_state=from_state)

	if doc.doctype == "PM Request":
		from erpnext_extensions.petty_management.services.business_status_service import (
			REQ_DRAFT,
			sync_pm_request_business_status,
		)

		status = sync_pm_request_business_status(doc)
		if status != REQ_DRAFT and cint(doc.docstatus) == 0:
			status = REQ_DRAFT
			doc.status = REQ_DRAFT
		frappe.db.set_value(doc.doctype, doc.name, "status", status, update_modified=False)
		doc.status = status
	else:
		from erpnext_extensions.petty_management.services.business_status_service import (
			CLR_DRAFT,
			sync_pm_clearance_business_status,
		)

		lifecycle = sync_pm_clearance_business_status(doc, persist=False)
		if lifecycle != CLR_DRAFT and cint(doc.docstatus) == 0:
			lifecycle = CLR_DRAFT
			doc.status = CLR_DRAFT
		frappe.db.set_value(doc.doctype, doc.name, "status", lifecycle, update_modified=False)
		doc.status = lifecycle

	doc.reload()
	return doc
