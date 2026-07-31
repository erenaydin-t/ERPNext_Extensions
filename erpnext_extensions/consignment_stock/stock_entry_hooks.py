# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint

from erpnext_extensions.consignment_stock.accounting import (
	apply_default_cost_center,
	force_expense_account_on_items,
	get_consignment_settings,
	get_temporary_clearing_account,
	validate_warehouse_inventory_account,
)
from erpnext_extensions.consignment_stock.additional_costs import validate_no_additional_costs
from erpnext_extensions.consignment_stock.constants import (
	F_HAS_RECEIPT_REF,
	F_IS_RECEIPT,
	F_IS_RETURN,
	F_PARTY,
	F_PARTY_TYPE,
	F_RECEIPT_DETAIL,
	F_RECEIPT_REF,
	F_RECEIPT_SE,
	F_RECOGNITION_JE,
	F_SETTLEMENT_JE,
)
from erpnext_extensions.consignment_stock.party import validate_consignment_party
from erpnext_extensions.consignment_stock.returnable_qty import (
	populate_return_row_snapshots,
	validate_return_quantities,
)
from erpnext_extensions.consignment_stock import status as consignment_status
from erpnext_extensions.consignment_stock.stock_entry_rates import (
	lock_return_outgoing_rates,
	prepare_receipt_rates,
)


def _sync_flags_from_type(doc) -> None:
	if not doc.stock_entry_type:
		return
	values = frappe.db.get_value(
		"Stock Entry Type",
		doc.stock_entry_type,
		[F_IS_RECEIPT, F_IS_RETURN],
		as_dict=True,
	)
	if not values:
		return
	doc.set(F_IS_RECEIPT, cint(values.get(F_IS_RECEIPT)))
	doc.set(F_IS_RETURN, cint(values.get(F_IS_RETURN)))


def _is_receipt(doc) -> bool:
	return bool(cint(doc.get(F_IS_RECEIPT)))


def _is_return(doc) -> bool:
	return bool(cint(doc.get(F_IS_RETURN)))


def before_validate(doc, method=None):
	"""Run before Stock Entry.calculate_rate_and_amount clears Issue additional_costs."""
	_sync_flags_from_type(doc)
	if _is_receipt(doc) or _is_return(doc):
		validate_no_additional_costs(doc)


def validate(doc, method=None):
	_sync_flags_from_type(doc)
	if not (_is_receipt(doc) or _is_return(doc)):
		return

	settings = get_consignment_settings(doc.company)
	validate_consignment_party(doc.get(F_PARTY_TYPE), doc.get(F_PARTY), doc.company)
	validate_no_additional_costs(doc)
	apply_default_cost_center(doc, settings)
	force_expense_account_on_items(doc, settings.consignment_temporary_clearing_account)
	validate_warehouse_inventory_account(doc, settings)

	if _is_receipt(doc):
		if doc.purpose != "Material Receipt":
			frappe.throw(_("Consignment Receipt Stock Entry must have Purpose Material Receipt."))
		prepare_receipt_rates(doc, settings)
		consignment_status.sync_draft_status(doc)

	if _is_return(doc):
		if doc.purpose != "Material Issue":
			frappe.throw(_("Consignment Return Stock Entry must have Purpose Material Issue."))
		# 3.8.0: every return must reference receipt rows
		doc.set(F_HAS_RECEIPT_REF, 1)
		lock_return_outgoing_rates(doc)
		_apply_header_receipt_default(doc)
		_validate_return_references(doc)
		_validate_recognition_before_return(doc)
		populate_return_row_snapshots(doc)
		validate_return_quantities(doc)
		consignment_status.sync_draft_status(doc)


def before_submit(doc, method=None):
	_sync_flags_from_type(doc)
	if not (_is_receipt(doc) or _is_return(doc)):
		return

	settings = get_consignment_settings(doc.company)
	validate_consignment_party(doc.get(F_PARTY_TYPE), doc.get(F_PARTY), doc.company)
	validate_no_additional_costs(doc)
	force_expense_account_on_items(doc, get_temporary_clearing_account(doc.company))

	if _is_receipt(doc):
		prepare_receipt_rates(doc, settings)

	if _is_return(doc):
		doc.set(F_HAS_RECEIPT_REF, 1)
		_validate_return_references(doc)
		_validate_recognition_before_return(doc)
		populate_return_row_snapshots(doc)
		validate_return_quantities(doc)


def on_submit(doc, method=None):
	_sync_flags_from_type(doc)
	if _is_receipt(doc):
		consignment_status.on_receipt_submit(doc)
	elif _is_return(doc):
		consignment_status.on_return_submit(doc)


def before_cancel(doc, method=None):
	_sync_flags_from_type(doc)
	if _is_receipt(doc):
		_block_receipt_cancel(doc)
	elif _is_return(doc):
		_block_return_cancel(doc)


def on_cancel(doc, method=None):
	_sync_flags_from_type(doc)
	if _is_receipt(doc) or _is_return(doc):
		consignment_status.on_cancel(doc)
		if _is_return(doc):
			# refresh parent receipt statuses
			consignment_status._refresh_receipt_return_status_from_return(doc)


def _apply_header_receipt_default(doc) -> None:
	default_receipt = doc.get(F_RECEIPT_REF)
	if not default_receipt:
		return
	for row in doc.get("items") or []:
		if not row.get(F_RECEIPT_SE):
			row.set(F_RECEIPT_SE, default_receipt)


def _validate_return_references(doc) -> None:
	party_type = doc.get(F_PARTY_TYPE)
	party = doc.get(F_PARTY)
	for row in doc.get("items") or []:
		receipt_name = row.get(F_RECEIPT_SE)
		if not receipt_name:
			frappe.throw(_("Row {0}: Consignment Receipt reference is required.").format(row.idx))
		receipt = frappe.db.get_value(
			"Stock Entry",
			receipt_name,
			["docstatus", "company", F_IS_RECEIPT, F_PARTY_TYPE, F_PARTY, F_RECOGNITION_JE],
			as_dict=True,
		)
		if not receipt:
			frappe.throw(_("Row {0}: Consignment Receipt {1} not found.").format(row.idx, receipt_name))
		if receipt.docstatus != 1:
			frappe.throw(
				_("Row {0}: Consignment Receipt {1} must be submitted.").format(row.idx, receipt_name)
			)
		if not cint(receipt.get(F_IS_RECEIPT)):
			frappe.throw(
				_("Row {0}: {1} is not a Consignment Receipt.").format(row.idx, receipt_name)
			)
		if receipt.company != doc.company:
			frappe.throw(
				_("Row {0}: Consignment Receipt {1} belongs to another company.").format(
					row.idx, receipt_name
				)
			)
		if receipt.get(F_PARTY_TYPE) != party_type or receipt.get(F_PARTY) != party:
			frappe.throw(
				_("Row {0}: Return party must match Consignment Receipt {1} party.").format(
					row.idx, receipt_name
				)
			)
		if not row.get(F_RECEIPT_DETAIL):
			# try resolve by item if single matching row
			_autofill_receipt_detail(row, receipt_name)


def _autofill_receipt_detail(row, receipt_name: str) -> None:
	if row.get(F_RECEIPT_DETAIL):
		return
	matches = frappe.get_all(
		"Stock Entry Detail",
		filters={"parent": receipt_name, "item_code": row.item_code},
		pluck="name",
	)
	if len(matches) == 1:
		row.set(F_RECEIPT_DETAIL, matches[0])


def _validate_recognition_before_return(doc) -> None:
	"""L1: submitted Recognition JE required for every referenced receipt."""
	receipts = {row.get(F_RECEIPT_SE) for row in (doc.get("items") or []) if row.get(F_RECEIPT_SE)}
	for receipt_name in receipts:
		je = frappe.db.get_value("Stock Entry", receipt_name, F_RECOGNITION_JE)
		if not je:
			frappe.throw(
				_(
					"Consignment Receipt {0} has no Recognition Journal Entry. "
					"Submit a Recognition JE before creating a Consignment Return."
				).format(receipt_name)
			)
		je_status = frappe.db.get_value("Journal Entry", je, "docstatus")
		if je_status != 1:
			frappe.throw(
				_(
					"Recognition Journal Entry {0} for Consignment Receipt {1} must be submitted "
					"before creating a Consignment Return."
				).format(je, receipt_name)
			)


def _block_receipt_cancel(doc) -> None:
	je = doc.get(F_RECOGNITION_JE)
	if je:
		je_status = frappe.db.get_value("Journal Entry", je, "docstatus")
		if je_status == 1:
			frappe.throw(
				_(
					"Cancel Recognition Journal Entry {0} before cancelling Consignment Receipt {1}."
				).format(je, doc.name)
			)
		if je_status == 0:
			frappe.throw(
				_(
					"Delete or cancel draft Recognition Journal Entry {0} before cancelling "
					"Consignment Receipt {1}."
				).format(je, doc.name)
			)

	# Block if any submitted return references this receipt
	linked = frappe.db.sql(
		f"""
		select distinct se.name
		from `tabStock Entry` se
		inner join `tabStock Entry Detail` sed on sed.parent = se.name
		where se.docstatus = 1
			and se.{F_IS_RETURN} = 1
			and sed.{F_RECEIPT_SE} = %s
		limit 1
		""",
		doc.name,
	)
	if linked:
		frappe.throw(
			_(
				"Cancel Consignment Return {0} before cancelling Consignment Receipt {1}."
			).format(linked[0][0], doc.name)
		)


def _block_return_cancel(doc) -> None:
	je = doc.get(F_SETTLEMENT_JE)
	if je and frappe.db.get_value("Journal Entry", je, "docstatus") == 1:
		frappe.throw(
			_(
				"Cancel Settlement Journal Entry {0} before cancelling Consignment Return {1}."
			).format(je, doc.name)
		)
	if je and frappe.db.get_value("Journal Entry", je, "docstatus") == 0:
		frappe.throw(
			_(
				"Delete or cancel draft Settlement Journal Entry {0} before cancelling "
				"Consignment Return {1}."
			).format(je, doc.name)
		)
