# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

import frappe

from erpnext_extensions.consignment_stock.constants import (
	F_JE_ROLE,
	F_RECOGNITION_JE,
	F_SETTLEMENT_JE,
	JE_ROLE_RECOGNITION,
	JE_ROLE_SETTLEMENT,
)
from erpnext_extensions.consignment_stock import status as consignment_status


def on_submit(doc, method=None):
	role = doc.get(F_JE_ROLE) if doc.meta.has_field(F_JE_ROLE) else None
	if role == JE_ROLE_RECOGNITION:
		receipt = frappe.db.get_value("Stock Entry", {F_RECOGNITION_JE: doc.name}, "name")
		if receipt:
			consignment_status.on_recognition_linked(receipt)
	elif role == JE_ROLE_SETTLEMENT:
		ret = frappe.db.get_value("Stock Entry", {F_SETTLEMENT_JE: doc.name}, "name")
		if ret:
			consignment_status.on_settlement_linked(ret)


def before_cancel(doc, method=None):
	# No auto-cancel of Stock Entries; links cleared on_cancel
	return


def on_cancel(doc, method=None):
	role = doc.get(F_JE_ROLE) if doc.meta.has_field(F_JE_ROLE) else None
	if role == JE_ROLE_RECOGNITION:
		_clear_recognition(doc)
	elif role == JE_ROLE_SETTLEMENT:
		_clear_settlement(doc)
	else:
		# Fallback: find SE pointing to this JE
		receipt = frappe.db.get_value("Stock Entry", {F_RECOGNITION_JE: doc.name}, "name")
		if receipt:
			consignment_status.clear_recognition_link(receipt)
		ret = frappe.db.get_value("Stock Entry", {F_SETTLEMENT_JE: doc.name}, "name")
		if ret:
			consignment_status.clear_settlement_link(ret)


def on_trash(doc, method=None):
	"""Draft JE deleted before submit — clear SE links."""
	if doc.docstatus != 0:
		return
	role = doc.get(F_JE_ROLE) if doc.meta.has_field(F_JE_ROLE) else None
	if role == JE_ROLE_RECOGNITION:
		_clear_recognition(doc)
	elif role == JE_ROLE_SETTLEMENT:
		_clear_settlement(doc)


def _clear_recognition(doc) -> None:
	receipt = frappe.db.get_value("Stock Entry", {F_RECOGNITION_JE: doc.name}, "name")
	if not receipt:
		# try reference_name on accounts
		for row in doc.get("accounts") or []:
			if row.reference_type == "Stock Entry" and row.reference_name:
				if frappe.db.get_value("Stock Entry", row.reference_name, F_RECOGNITION_JE) == doc.name:
					receipt = row.reference_name
					break
	if receipt:
		consignment_status.clear_recognition_link(receipt)


def _clear_settlement(doc) -> None:
	ret = frappe.db.get_value("Stock Entry", {F_SETTLEMENT_JE: doc.name}, "name")
	if not ret:
		for row in doc.get("accounts") or []:
			if row.reference_type == "Stock Entry" and row.reference_name:
				if frappe.db.get_value("Stock Entry", row.reference_name, F_SETTLEMENT_JE) == doc.name:
					ret = row.reference_name
					break
	if ret:
		consignment_status.clear_settlement_link(ret)
