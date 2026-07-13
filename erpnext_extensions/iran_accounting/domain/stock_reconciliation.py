# Copyright (c) 2026, ERPNext Extensions contributors

from __future__ import annotations

import erpnext
import frappe
from frappe import _
from frappe.utils import cint, flt

from erpnext_extensions.iran_accounting.domain.currency import is_irr_company
from erpnext_extensions.iran_accounting.domain.qty_rate_amount import (
	override_difference_amount,
	sum_stock_reconciliation_amount_difference,
)
from erpnext_extensions.iran_accounting.domain.stock_reconciliation_gl import log_gl_generation_triggered
from erpnext_extensions.iran_accounting.domain.stock_reconciliation_sync import (
	sync_irr_sle_from_stock_reconciliation_row,
)
from erpnext_extensions.iran_accounting.validation import fetch_gl_rows, gl_debit_credit_totals


def validate_stock_reconciliation(doc, method=None) -> None:
	from erpnext_extensions.iran_accounting.integration.bootstrap import apply

	apply()
	override_difference_amount(doc)


def before_submit_stock_reconciliation(doc, method=None) -> None:
	from erpnext_extensions.iran_accounting.integration.bootstrap import apply

	apply()
	override_difference_amount(doc)


def ensure_stock_reconciliation_gl_entries(doc) -> None:
	"""Create GL from row amounts when missing (e.g. vouchers submitted before IRR GL patch)."""
	if doc.docstatus != 1 or not cint(erpnext.is_perpetual_inventory_enabled(doc.company)):
		return
	if fetch_gl_rows("Stock Reconciliation", doc.name):
		return
	if hasattr(doc, "make_gl_entries"):
		doc.make_gl_entries()


def on_submit_stock_reconciliation(doc, method=None) -> None:
	from erpnext_extensions.iran_accounting.integration.bootstrap import apply

	apply()
	if not is_irr_company(doc.company):
		return
	override_difference_amount(doc)
	log_gl_generation_triggered(doc)

	if not cint(erpnext.is_perpetual_inventory_enabled(doc.company)):
		return

	net = sum_stock_reconciliation_amount_difference(doc)
	if net == 0:
		return

	gl_rows = fetch_gl_rows("Stock Reconciliation", doc.name)
	if not gl_rows:
		ensure_stock_reconciliation_gl_entries(doc)

	gl_rows = fetch_gl_rows("Stock Reconciliation", doc.name)
	debit, credit = gl_debit_credit_totals(gl_rows)
	gl_mag = max(flt(debit), flt(credit))
	if not gl_rows or gl_mag != abs(net):
		frappe.throw(
			_("Stock Reconciliation {0}: GL missing or total {1} != net row movement {2}").format(
				doc.name, gl_mag, net
			),
			title=_("IRR Ledger Determinism"),
		)


@frappe.whitelist()
def repair_stock_reconciliation_irr_amount_alignment(voucher_no: str):
	from erpnext_extensions.iran_accounting.diagnostics import run_repost_for_voucher_impl
	from erpnext_extensions.iran_accounting.domain.qty_rate_amount import override_difference_amount

	doc = frappe.get_doc("Stock Reconciliation", voucher_no)
	if doc.docstatus != 1:
		frappe.throw("Submitted Stock Reconciliation only")
	override_difference_amount(doc)
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
	ensure_stock_reconciliation_gl_entries(doc)
	out = run_repost_for_voucher_impl("Stock Reconciliation", voucher_no, normalize_after=True)
	chk = __import__(
		"erpnext_extensions.iran_accounting.qty_rate_consistency",
		fromlist=["check_qty_rate_amount_consistency"],
	).check_qty_rate_amount_consistency("Stock Reconciliation", voucher_no, doc.company)
	return {"repost": out, "check": chk, "difference_amount": doc.difference_amount}
