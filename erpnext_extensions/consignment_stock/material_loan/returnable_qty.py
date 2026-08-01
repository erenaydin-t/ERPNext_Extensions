# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt

from erpnext_extensions.consignment_stock.material_loan.constants import (
	F_IS_LOAN_RETURN,
	F_ISSUE_DETAIL,
	F_ISSUE_QTY,
	F_ISSUE_RATE,
	F_ISSUE_SE,
	F_ISSUE_VALUE,
	F_PREV_RETURNED_QTY,
	F_REMAINING_QTY,
	F_RETURN_VALUE,
	F_SETTLEMENT_AMOUNT,
)


def get_returned_qty(issue_detail: str, exclude_return_name: str | None = None) -> float:
	if not issue_detail:
		return 0.0
	rows = frappe.get_all(
		"Stock Entry Detail",
		filters={"parenttype": "Stock Entry", "docstatus": 1, F_ISSUE_DETAIL: issue_detail},
		fields=["parent", "transfer_qty", "qty"],
	)
	total = 0.0
	for row in rows:
		if exclude_return_name and row.parent == exclude_return_name:
			continue
		if not frappe.db.get_value("Stock Entry", row.parent, F_IS_LOAN_RETURN):
			continue
		total += flt(row.transfer_qty if row.transfer_qty not in (None, "") else row.qty)
	return total


def get_remaining_returnable_qty(
	issue_detail: str,
	original_qty: float | None = None,
	exclude_return_name: str | None = None,
) -> float:
	if original_qty is None:
		original_qty = flt(
			frappe.db.get_value("Stock Entry Detail", issue_detail, "transfer_qty")
			or frappe.db.get_value("Stock Entry Detail", issue_detail, "qty")
		)
	return flt(original_qty) - flt(get_returned_qty(issue_detail, exclude_return_name))


def issue_return_progress(issue_name: str) -> dict:
	details = frappe.get_all(
		"Stock Entry Detail",
		filters={"parent": issue_name},
		fields=["name", "transfer_qty", "qty", F_ISSUE_RATE],
	)
	original = 0.0
	returned = 0.0
	remaining_value = 0.0
	for d in details:
		oq = flt(d.transfer_qty if d.transfer_qty not in (None, "") else d.qty)
		rq = get_returned_qty(d.name)
		original += oq
		returned += rq
		remaining_value += flt(oq - rq) * flt(d.get(F_ISSUE_RATE))
	return {
		"original": original,
		"returned": returned,
		"remaining": flt(original) - flt(returned),
		"remaining_value": remaining_value,
	}


def has_submitted_loan_returns(issue_name: str) -> bool:
	return bool(
		frappe.db.sql(
			f"""
			select sed.name
			from `tabStock Entry Detail` sed
			inner join `tabStock Entry` se on se.name = sed.parent
			where sed.docstatus = 1
			  and sed.{F_ISSUE_SE} = %s
			  and se.{F_IS_LOAN_RETURN} = 1
			limit 1
			""",
			issue_name,
		)
	)


def populate_return_row_snapshots(doc) -> None:
	precision = doc.precision("total_incoming_value") or 2
	for row in doc.get("items") or []:
		detail = row.get(F_ISSUE_DETAIL)
		if not detail:
			continue
		issue_row = frappe.db.get_value(
			"Stock Entry Detail",
			detail,
			["transfer_qty", "qty", F_ISSUE_RATE, F_ISSUE_VALUE, F_ISSUE_QTY],
			as_dict=True,
		)
		if not issue_row:
			continue
		original_qty = flt(
			issue_row.get(F_ISSUE_QTY)
			or issue_row.transfer_qty
			or issue_row.qty
		)
		prev = get_returned_qty(detail, exclude_return_name=doc.name)
		remaining = flt(original_qty) - flt(prev)
		rate = flt(issue_row.get(F_ISSUE_RATE))
		qty = flt(row.transfer_qty if row.transfer_qty not in (None, "") else row.qty)
		settlement = flt(qty * rate, precision)
		row.set(F_ISSUE_RATE, rate)
		row.set(F_ISSUE_VALUE, issue_row.get(F_ISSUE_VALUE))
		row.set(F_ISSUE_QTY, original_qty)
		row.set(F_PREV_RETURNED_QTY, prev)
		row.set(F_REMAINING_QTY, remaining)
		row.set(F_RETURN_VALUE, settlement)
		row.set(F_SETTLEMENT_AMOUNT, settlement)


def validate_return_quantities(doc) -> None:
	for row in doc.get("items") or []:
		detail = row.get(F_ISSUE_DETAIL)
		if not detail:
			frappe.throw(_("Row {0}: Material Loan Issue Detail is required.").format(row.idx))
		qty = flt(row.transfer_qty if row.transfer_qty not in (None, "") else row.qty)
		if qty <= 0:
			frappe.throw(_("Row {0}: Quantity must be greater than zero.").format(row.idx))
		remaining = get_remaining_returnable_qty(detail, exclude_return_name=doc.name)
		if qty > remaining + 1e-9:
			frappe.throw(
				_(
					"Row {0}: Returned quantity {1} exceeds remaining returnable quantity {2}."
				).format(row.idx, qty, remaining)
			)
