# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

import frappe
from frappe.utils import flt

from erpnext_extensions.consignment_stock.material_loan.constants import (
	F_ISSUE_QTY,
	F_ISSUE_RATE,
	F_ISSUE_VALUE,
)


def snapshot_issue_rows(stock_entry) -> None:
	"""Persist frozen issue valuation from submitted SLE rows."""
	precision = stock_entry.precision("total_outgoing_value") or 2
	for row in stock_entry.get("items") or []:
		value, qty = _sle_value_and_qty(stock_entry.name, row.name, row)
		rate = flt(value / qty, precision) if qty else 0.0
		frappe.db.set_value(
			"Stock Entry Detail",
			row.name,
			{
				F_ISSUE_RATE: rate,
				F_ISSUE_VALUE: flt(value, precision),
				F_ISSUE_QTY: qty,
			},
			update_modified=False,
		)
		row.set(F_ISSUE_RATE, rate)
		row.set(F_ISSUE_VALUE, flt(value, precision))
		row.set(F_ISSUE_QTY, qty)


def refresh_issue_frozen_valuation(issue_name: str) -> None:
	doc = frappe.get_doc("Stock Entry", issue_name)
	snapshot_issue_rows(doc)


def get_issue_total_frozen_value(stock_entry) -> float:
	precision = stock_entry.precision("total_outgoing_value") or 2
	total = 0.0
	for row in stock_entry.get("items") or []:
		val = row.get(F_ISSUE_VALUE)
		if val in (None, ""):
			val, _qty = _sle_value_and_qty(stock_entry.name, row.name, row)
		total += flt(val)
	return flt(total, precision)


def _sle_value_and_qty(voucher_no: str, detail_name: str, row) -> tuple[float, float]:
	sles = frappe.get_all(
		"Stock Ledger Entry",
		filters={
			"voucher_type": "Stock Entry",
			"voucher_no": voucher_no,
			"voucher_detail_no": detail_name,
			"is_cancelled": 0,
		},
		fields=["stock_value_difference", "actual_qty"],
	)
	value = abs(sum(flt(s.stock_value_difference) for s in sles))
	qty = flt(row.transfer_qty if row.transfer_qty not in (None, "") else row.qty)
	if not qty and sles:
		qty = abs(sum(flt(s.actual_qty) for s in sles))
	return value, qty
