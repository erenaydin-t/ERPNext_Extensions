# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt

from erpnext_extensions.consignment_stock.constants import (
	F_IS_RECEIPT,
	F_IS_RETURN,
	F_ORIGINAL_QTY,
	F_ORIGINAL_RATE,
	F_PREV_RETURNED_QTY,
	F_RECEIPT_DETAIL,
	F_RECEIPT_SE,
	F_REMAINING_QTY,
	F_SETTLEMENT_AMOUNT,
)


def get_returned_qty(receipt_detail: str, exclude_return_name: str | None = None) -> float:
	"""Sum submitted return qty against a receipt detail row (stock UOM via transfer_qty)."""
	if not receipt_detail:
		return 0.0

	filters = {
		"parenttype": "Stock Entry",
		"docstatus": 1,
		F_RECEIPT_DETAIL: receipt_detail,
	}
	rows = frappe.get_all(
		"Stock Entry Detail",
		filters=filters,
		fields=["parent", "transfer_qty", "qty", "name"],
	)
	total = 0.0
	for row in rows:
		if exclude_return_name and row.parent == exclude_return_name:
			continue
		# Ensure parent is consignment return
		is_return = frappe.db.get_value("Stock Entry", row.parent, F_IS_RETURN)
		if not is_return:
			continue
		total += flt(row.transfer_qty if row.transfer_qty not in (None, "") else row.qty)
	return total


def get_remaining_returnable_qty(
	receipt_detail: str,
	original_qty: float | None = None,
	exclude_return_name: str | None = None,
) -> float:
	if original_qty is None:
		original_qty = flt(
			frappe.db.get_value("Stock Entry Detail", receipt_detail, "transfer_qty")
			or frappe.db.get_value("Stock Entry Detail", receipt_detail, "qty")
		)
	returned = get_returned_qty(receipt_detail, exclude_return_name=exclude_return_name)
	return flt(original_qty) - flt(returned)


def receipt_return_progress(receipt_name: str) -> dict:
	details = frappe.get_all(
		"Stock Entry Detail",
		filters={"parent": receipt_name},
		fields=["name", "transfer_qty", "qty"],
	)
	original = 0.0
	returned = 0.0
	for d in details:
		oq = flt(d.transfer_qty if d.transfer_qty not in (None, "") else d.qty)
		original += oq
		returned += get_returned_qty(d.name)
	return {
		"original": original,
		"returned": returned,
		"remaining": flt(original) - flt(returned),
	}


def populate_return_row_snapshots(doc) -> None:
	for row in doc.get("items") or []:
		receipt_se = row.get(F_RECEIPT_SE)
		receipt_detail = row.get(F_RECEIPT_DETAIL)
		if not receipt_se or not receipt_detail:
			continue

		rd = frappe.db.get_value(
			"Stock Entry Detail",
			receipt_detail,
			["parent", "item_code", "transfer_qty", "qty", "basic_rate", "conversion_factor"],
			as_dict=True,
		)
		if not rd:
			frappe.throw(_("Row {0}: Consignment Receipt Row {1} not found.").format(row.idx, receipt_detail))
		if rd.parent != receipt_se:
			frappe.throw(
				_("Row {0}: Receipt Row {1} does not belong to Stock Entry {2}.").format(
					row.idx, receipt_detail, receipt_se
				)
			)

		original_qty = flt(rd.transfer_qty if rd.transfer_qty not in (None, "") else rd.qty)
		# Store rate per stock UOM
		conversion = flt(rd.conversion_factor) or 1.0
		stock_rate = flt(rd.basic_rate) / conversion if conversion else flt(rd.basic_rate)
		prev = get_returned_qty(receipt_detail, exclude_return_name=doc.name)
		remaining = original_qty - prev

		row.set(F_ORIGINAL_QTY, original_qty)
		row.set(F_ORIGINAL_RATE, stock_rate)
		row.set(F_PREV_RETURNED_QTY, prev)
		row.set(F_REMAINING_QTY, remaining)

		return_qty = flt(row.transfer_qty if row.transfer_qty not in (None, "") else row.qty)
		row.set(F_SETTLEMENT_AMOUNT, flt(return_qty * stock_rate, row.precision("amount") if hasattr(row, "precision") else 2))


def validate_return_quantities(doc) -> None:
	for row in doc.get("items") or []:
		receipt_detail = row.get(F_RECEIPT_DETAIL)
		if not receipt_detail:
			frappe.throw(_("Row {0}: Consignment Receipt Row is required.").format(row.idx))
		if not row.get(F_RECEIPT_SE):
			frappe.throw(_("Row {0}: Consignment Receipt is required.").format(row.idx))

		rd_item = frappe.db.get_value("Stock Entry Detail", receipt_detail, "item_code")
		if rd_item != row.item_code:
			frappe.throw(
				_("Row {0}: Item {1} does not match receipt row item {2}.").format(
					row.idx, row.item_code, rd_item
				)
			)

		remaining = flt(row.get(F_REMAINING_QTY))
		return_qty = flt(row.transfer_qty if row.transfer_qty not in (None, "") else row.qty)
		if return_qty <= 0:
			frappe.throw(_("Row {0}: Return quantity must be greater than zero.").format(row.idx))
		if return_qty > remaining + 1e-9:
			frappe.throw(
				_(
					"Row {0}: Return quantity {1} exceeds remaining returnable quantity {2}."
				).format(row.idx, return_qty, remaining)
			)
