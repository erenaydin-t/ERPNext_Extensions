# Copyright (c) 2026, ERPNext Extensions contributors

from __future__ import annotations

import frappe

from erpnext_extensions.iran_accounting.qty_rate_amount import align_stock_reconciliation_row_amounts
from erpnext_extensions.iran_accounting.stock_reconciliation_sync import (
	sync_irr_sle_from_stock_reconciliation_row,
)


def validate_stock_reconciliation(doc, method=None) -> None:
	"""IRR: row-level rounded amounts; header difference_amount = sum(amount_difference)."""
	align_stock_reconciliation_row_amounts(doc)


def before_submit_stock_reconciliation(doc, method=None) -> None:
	align_stock_reconciliation_row_amounts(doc)


@frappe.whitelist()
def repair_stock_reconciliation_irr_amount_alignment(voucher_no: str):
	"""Re-align submitted Stock Reconciliation row amounts and SLE from rounded qty×rate (IRR)."""
	from erpnext_extensions.iran_accounting.diagnostics import run_repost_for_voucher_impl
	from erpnext_extensions.iran_accounting.rounding import get_company_currency

	doc = frappe.get_doc("Stock Reconciliation", voucher_no)
	if doc.docstatus != 1:
		frappe.throw("Submitted Stock Reconciliation only")
	align_stock_reconciliation_row_amounts(doc)
	for row in doc.items:
		frappe.db.set_value(
			"Stock Reconciliation Item",
			row.name,
			{
				"amount": row.amount,
				"current_amount": row.current_amount,
				"amount_difference": row.amount_difference,
			},
		)
	frappe.db.set_value("Stock Reconciliation", doc.name, "difference_amount", doc.difference_amount)
	sles = frappe.get_all(
		"Stock Ledger Entry",
		filters={"voucher_type": "Stock Reconciliation", "voucher_no": voucher_no, "is_cancelled": 0},
		pluck="name",
	)
	for sle_name in sles:
		sle = frappe.get_doc("Stock Ledger Entry", sle_name)
		sync_irr_sle_from_stock_reconciliation_row(sle)
		sle.save(ignore_permissions=True)
	out = run_repost_for_voucher_impl("Stock Reconciliation", voucher_no, normalize_after=True)
	chk = __import__(
		"erpnext_extensions.iran_accounting.qty_rate_consistency",
		fromlist=["check_qty_rate_amount_consistency"],
	).check_qty_rate_amount_consistency("Stock Reconciliation", voucher_no, doc.company)
	return {"repost": out, "check": chk, "difference_amount": doc.difference_amount}
