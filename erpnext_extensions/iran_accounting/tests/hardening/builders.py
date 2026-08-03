# Copyright (c) 2026, ERPNext Extensions contributors
"""Builders for non-trivial Stock Entry / LCV / SR scenarios."""

from __future__ import annotations

from decimal import Decimal

import frappe
from frappe.utils import flt, nowdate, nowtime

from erpnext_extensions.iran_accounting.e2e_bootstrap import ensure_test_item, submit_material_receipt
from erpnext_extensions.iran_accounting.tests.hardening.decimal_money import D, quantize_money
from erpnext_extensions.iran_accounting.tests.hardening.fixtures import (
	ADD_COST,
	AMT_A,
	AMT_C,
	IRR_PRECISION,
	LCV_AMT,
	QTY_A,
	QTY_C,
	RATE_A,
	RATE_C,
)


def _expense_account(company: str) -> str:
	acc = frappe.db.get_value(
		"Account", {"company": company, "root_type": "Expense", "is_group": 0}, "name"
	)
	return acc or frappe.get_cached_value("Company", company, "stock_adjustment_account")


def _cost_center(company: str) -> str:
	cc = frappe.get_cached_value("Company", company, "cost_center")
	if cc:
		return cc
	return frappe.db.get_value(
		"Cost Center", {"company": company, "is_group": 0}, "name", order_by="creation asc"
	)


def _uom(item: str) -> str:
	return frappe.db.get_value("Item", item, "stock_uom")


def submit_receipt(company: str, item: str, qty, rate, warehouse: str):
	se = submit_material_receipt(company, item, qty=float(qty), rate=float(rate), warehouse=warehouse)
	if getattr(se, "docstatus", 0) == 0:
		se.submit()
	frappe.db.commit()
	return se


def make_manufacture(
	company: str,
	*,
	rm_item: str,
	fg_item: str,
	rm_warehouse: str,
	fg_warehouse: str,
	rm_qty,
	rm_rate,
	fg_qty,
	additional_cost: Decimal | int | float = 0,
):
	"""Seed RM via receipt then manufacture FG with optional additional cost."""
	need = D(rm_qty) * D(rm_rate)
	# ensure enough stock with same rate economics
	submit_receipt(company, rm_item, D(rm_qty) + Decimal("3"), rm_rate, rm_warehouse)

	cc = _cost_center(company)
	oh = _expense_account(company)
	se = frappe.new_doc("Stock Entry")
	se.company = company
	se.stock_entry_type = "Manufacture"
	se.purpose = "Manufacture"
	se.posting_date = nowdate()
	se.posting_time = nowtime()
	se.set_posting_time = 1
	se.append(
		"items",
		{
			"item_code": rm_item,
			"qty": float(rm_qty),
			"transfer_qty": float(rm_qty),
			"conversion_factor": 1,
			"uom": _uom(rm_item),
			"s_warehouse": rm_warehouse,
			"basic_rate": float(rm_rate),
			"cost_center": cc,
		},
	)
	se.append(
		"items",
		{
			"item_code": fg_item,
			"qty": float(fg_qty),
			"transfer_qty": float(fg_qty),
			"conversion_factor": 1,
			"uom": _uom(fg_item),
			"t_warehouse": fg_warehouse,
			"is_finished_item": 1,
			"cost_center": cc,
		},
	)
	add = quantize_money(additional_cost, IRR_PRECISION)
	if add != 0:
		se.append(
			"additional_costs",
			{
				"expense_account": oh,
				"description": "hardening overhead",
				"amount": float(add),
				"base_amount": float(add),
			},
		)
	se.insert(ignore_permissions=True)
	se.submit()
	frappe.db.commit()
	return se, oh


def make_repack(company: str, *, item_in: str, item_out: str, warehouse: str, qty_in, rate_in, qty_out):
	submit_receipt(company, item_in, D(qty_in) + Decimal("2"), rate_in, warehouse)
	cc = _cost_center(company)
	se = frappe.new_doc("Stock Entry")
	se.company = company
	se.stock_entry_type = "Repack"
	se.purpose = "Repack"
	se.posting_date = nowdate()
	se.posting_time = nowtime()
	se.set_posting_time = 1
	se.append(
		"items",
		{
			"item_code": item_in,
			"qty": float(qty_in),
			"transfer_qty": float(qty_in),
			"conversion_factor": 1,
			"uom": _uom(item_in),
			"s_warehouse": warehouse,
			"basic_rate": float(rate_in),
			"cost_center": cc,
		},
	)
	se.append(
		"items",
		{
			"item_code": item_out,
			"qty": float(qty_out),
			"transfer_qty": float(qty_out),
			"conversion_factor": 1,
			"uom": _uom(item_out),
			"t_warehouse": warehouse,
			"cost_center": cc,
		},
	)
	se.insert(ignore_permissions=True)
	se.submit()
	frappe.db.commit()
	return se


def make_transfer(company: str, item: str, qty, rate, from_wh: str, to_wh: str, *, purpose="Material Transfer"):
	submit_receipt(company, item, D(qty) + Decimal("2"), rate, from_wh)
	cc = _cost_center(company)
	se = frappe.new_doc("Stock Entry")
	se.company = company
	se.stock_entry_type = purpose
	se.purpose = purpose
	se.posting_date = nowdate()
	se.posting_time = nowtime()
	se.set_posting_time = 1
	se.append(
		"items",
		{
			"item_code": item,
			"qty": float(qty),
			"transfer_qty": float(qty),
			"conversion_factor": 1,
			"uom": _uom(item),
			"s_warehouse": from_wh,
			"t_warehouse": to_wh,
			"cost_center": cc,
		},
	)
	se.insert(ignore_permissions=True)
	se.submit()
	frappe.db.commit()
	return se


def make_issue(company: str, item: str, qty, rate, warehouse: str):
	submit_receipt(company, item, D(qty) + Decimal("2"), rate, warehouse)
	from erpnext.stock.doctype.stock_entry.stock_entry_utils import make_stock_entry

	se = make_stock_entry(
		item_code=item,
		qty=float(qty),
		source=warehouse,
		rate=float(rate),
		company=company,
		purpose="Material Issue",
	)
	if se.docstatus == 0:
		se.submit()
	frappe.db.commit()
	return se


def apply_lcv_to_stock_entry(company: str, stock_entry_name: str, amount=LCV_AMT) -> tuple:
	oh = _expense_account(company)
	lcv = frappe.new_doc("Landed Cost Voucher")
	lcv.company = company
	lcv.posting_date = nowdate()
	lcv.append(
		"purchase_receipts",
		{"receipt_document_type": "Stock Entry", "receipt_document": stock_entry_name},
	)
	lcv.append(
		"taxes",
		{"expense_account": oh, "description": "hardening LCV", "amount": float(amount)},
	)
	lcv.get_items_from_purchase_receipts()
	lcv.insert(ignore_permissions=True)
	lcv.submit()
	frappe.db.commit()
	# Belt-and-suspenders: ensure IRR header matches capitalized LCV rows
	# (also covered by Landed Cost Voucher on_submit hook).
	from erpnext_extensions.iran_accounting.stock_entry import persist_irr_stock_entry_header_and_rows

	se = frappe.get_doc("Stock Entry", stock_entry_name)
	persist_irr_stock_entry_header_and_rows(se)
	frappe.db.commit()
	return lcv, oh


def run_riv(company: str, voucher_type: str, voucher_no: str, *, accounting_only: int = 0):
	if not frappe.db.exists("DocType", "Repost Item Valuation"):
		return None
	from erpnext.stock.doctype.repost_item_valuation.repost_item_valuation import repost

	riv = frappe.new_doc("Repost Item Valuation")
	riv.company = company
	riv.voucher_type = voucher_type
	riv.voucher_no = voucher_no
	riv.based_on = "Transaction"
	riv.repost_only_accounting_ledgers = accounting_only
	riv.flags.ignore_permissions = True
	riv.insert(ignore_permissions=True)
	repost(riv)
	frappe.db.commit()
	return riv


def ensure_ral_allows_stock_entry():
	"""Enable Stock Entry in Accounts Settings Allowed Types for RAL if needed."""
	try:
		settings = frappe.get_single("Accounts Settings")
	except Exception:
		return False
	allowed = {d.document_type for d in (settings.get("allowed_types") or [])}
	if "Stock Entry" in allowed and "Stock Reconciliation" in allowed:
		return True
	# attempt enable — test-only, not production business logic
	changed = False
	for dt in ("Stock Entry", "Stock Reconciliation"):
		if dt not in allowed:
			settings.append("allowed_types", {"document_type": dt})
			changed = True
	if changed:
		settings.flags.ignore_permissions = True
		settings.save(ignore_permissions=True)
		frappe.db.commit()
	return True


def run_ral(company: str, voucher_type: str, voucher_no: str):
	if not frappe.db.exists("DocType", "Repost Accounting Ledger"):
		return None
	ensure_ral_allows_stock_entry()
	from erpnext.accounts.doctype.repost_accounting_ledger.repost_accounting_ledger import start_repost

	ral = frappe.new_doc("Repost Accounting Ledger")
	ral.company = company
	ral.append("vouchers", {"voucher_type": voucher_type, "voucher_no": voucher_no})
	ral.insert(ignore_permissions=True)
	start_repost(ral.name)
	frappe.db.commit()
	return ral


def default_hardening_items(company: str) -> dict:
	return {
		"rm": ensure_test_item(company, "H376-RM"),
		"fg": ensure_test_item(company, "H376-FG"),
		"tr": ensure_test_item(company, "H376-TR"),
		"rp_in": ensure_test_item(company, "H376-RPIN"),
		"rp_out": ensure_test_item(company, "H376-RPOUT"),
	}


# re-export common fixtures for builders
__all__ = [
	"ADD_COST",
	"AMT_A",
	"AMT_C",
	"LCV_AMT",
	"QTY_A",
	"QTY_C",
	"RATE_A",
	"RATE_C",
	"apply_lcv_to_stock_entry",
	"default_hardening_items",
	"make_issue",
	"make_manufacture",
	"make_repack",
	"make_transfer",
	"run_ral",
	"run_riv",
	"submit_receipt",
]
