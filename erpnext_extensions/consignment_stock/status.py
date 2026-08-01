# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

import frappe
from frappe.utils import cint

from erpnext_extensions.consignment_stock.constants import (
	F_IS_RECEIPT,
	F_IS_RETURN,
	F_RECOGNITION_JE,
	F_SETTLEMENT_JE,
	F_STATUS,
	STATUS_CANCELLED,
	STATUS_DRAFT,
	STATUS_FULLY_RETURNED,
	STATUS_PARTIALLY_RETURNED,
	STATUS_RECEIPT_SUBMITTED,
	STATUS_RECOGNIZED,
	STATUS_RETURN_SUBMITTED,
	STATUS_SETTLED,
)


def is_consignment_doc(doc) -> bool:
	return bool(cint(doc.get(F_IS_RECEIPT)) or cint(doc.get(F_IS_RETURN)))


def set_status(doc, status: str) -> None:
	if doc.meta.has_field(F_STATUS):
		doc.db_set(F_STATUS, status, update_modified=False)


def sync_draft_status(doc) -> None:
	if not is_consignment_doc(doc):
		return
	if doc.docstatus == 0:
		doc.set(F_STATUS, STATUS_DRAFT)


def on_receipt_submit(doc) -> None:
	set_status(doc, STATUS_RECEIPT_SUBMITTED)


def on_return_submit(doc) -> None:
	set_status(doc, STATUS_RETURN_SUBMITTED)
	_refresh_receipt_return_status_from_return(doc)


def on_recognition_linked(receipt_name: str) -> None:
	doc = frappe.get_doc("Stock Entry", receipt_name)
	set_status(doc, STATUS_RECOGNIZED)
	_refresh_receipt_return_status(doc)


def on_settlement_linked(return_name: str) -> None:
	set_status(frappe.get_doc("Stock Entry", return_name), STATUS_SETTLED)


def on_cancel(doc) -> None:
	if is_consignment_doc(doc):
		set_status(doc, STATUS_CANCELLED)


def _refresh_receipt_return_status_from_return(return_doc) -> None:
	from erpnext_extensions.consignment_stock.constants import F_RECEIPT_SE
	from erpnext_extensions.consignment_stock.returnable_qty import receipt_return_progress

	seen = set()
	for row in return_doc.get("items") or []:
		receipt = row.get(F_RECEIPT_SE)
		if receipt and receipt not in seen:
			seen.add(receipt)
			_refresh_receipt_return_status(frappe.get_doc("Stock Entry", receipt))


def _refresh_receipt_return_status(receipt_doc) -> None:
	if not cint(receipt_doc.get(F_IS_RECEIPT)):
		return
	# Keep Recognized/Settled progression based on qty
	from erpnext_extensions.consignment_stock.returnable_qty import receipt_return_progress

	progress = receipt_return_progress(receipt_doc.name)
	recognition = receipt_doc.get(F_RECOGNITION_JE)
	recognition_submitted = bool(
		recognition and frappe.db.get_value("Journal Entry", recognition, "docstatus") == 1
	)

	if progress["remaining"] <= 0 and progress["original"] > 0:
		status = STATUS_FULLY_RETURNED
	elif progress["returned"] > 0:
		status = STATUS_PARTIALLY_RETURNED
	elif recognition_submitted:
		status = STATUS_RECOGNIZED
	elif receipt_doc.docstatus == 1:
		status = STATUS_RECEIPT_SUBMITTED
	else:
		status = STATUS_DRAFT

	set_status(receipt_doc, status)


def clear_recognition_link(receipt_name: str) -> None:
	frappe.db.set_value("Stock Entry", receipt_name, F_RECOGNITION_JE, None, update_modified=False)
	doc = frappe.get_doc("Stock Entry", receipt_name)
	if doc.docstatus == 1:
		set_status(doc, STATUS_RECEIPT_SUBMITTED)
		_refresh_receipt_return_status(doc)


def clear_settlement_link(return_name: str) -> None:
	frappe.db.set_value("Stock Entry", return_name, F_SETTLEMENT_JE, None, update_modified=False)
	doc = frappe.get_doc("Stock Entry", return_name)
	if doc.docstatus == 1:
		set_status(doc, STATUS_RETURN_SUBMITTED)
