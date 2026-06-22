# Copyright (c) 2026, ERPNext Extensions contributors

from __future__ import annotations

import frappe
from frappe.utils import cint, flt, nowtime, random_string, today

import erpnext
from erpnext.stock.doctype.stock_entry.stock_entry_utils import make_stock_entry

from erpnext_extensions.iran_accounting.validation import fetch_gl_rows, fetch_sle_rows


def _make_item(item_code: str, properties: dict | None = None):
	if frappe.db.exists("Item", item_code):
		return frappe.get_doc("Item", item_code)
	item = frappe.get_doc(
		{
			"doctype": "Item",
			"item_code": item_code,
			"item_name": item_code,
			"description": item_code,
			"item_group": "Products",
		}
	)
	if properties:
		item.update(properties)
	item.insert(ignore_permissions=True)
	return item


def _create_stock_reconciliation(**args):
	args = frappe._dict(args)
	sr = frappe.new_doc("Stock Reconciliation")
	sr.purpose = args.purpose or "Stock Reconciliation"
	sr.posting_date = args.posting_date or today()
	sr.posting_time = args.posting_time or nowtime()
	sr.set_posting_time = 1
	sr.company = args.company
	if sr.purpose == "Opening Stock":
		sr.expense_account = args.expense_account or (
			frappe.get_cached_value("Company", sr.company, "temporary_opening_account")
			or frappe.get_cached_value(
				"Account",
				{"company": sr.company, "account_type": "Temporary", "is_group": 0},
				"name",
			)
		)
	else:
		sr.expense_account = args.expense_account or (
			frappe.get_cached_value("Company", sr.company, "stock_adjustment_account")
			or frappe.get_cached_value(
				"Account", {"account_type": "Stock Adjustment", "company": sr.company}, "name"
			)
		)
	sr.cost_center = args.cost_center or frappe.get_cached_value("Company", sr.company, "cost_center")
	if sr.purpose == "Opening Stock":
		sr.difference_account = sr.expense_account
	sr.append(
		"items",
		{
			"item_code": args.item_code,
			"warehouse": args.warehouse,
			"qty": args.qty,
			"valuation_rate": args.rate,
			"reconcile_all_serial_batch": 1,
		},
	)
	sr.insert(ignore_permissions=True)
	sr.submit()
	return sr


def get_irr_company(preferred: str | None = None) -> str:
	if preferred and frappe.db.exists("Company", preferred):
		cur = frappe.db.get_value("Company", preferred, "default_currency")
		if cur == "IRR":
			return preferred
	name = frappe.db.get_value("Company", {"default_currency": "IRR"}, "name", order_by="creation asc")
	if not name:
		raise frappe.ValidationError("No IRR company on site")
	return name


def get_warehouse(company: str) -> str:
	wh = frappe.db.get_value("Warehouse", {"company": company, "is_group": 0}, "name", order_by="creation asc")
	if not wh:
		raise frappe.ValidationError(f"No warehouse for company {company}")
	return wh


def get_second_warehouse(company: str, exclude: str) -> str:
	wh = frappe.db.get_value(
		"Warehouse",
		{"company": company, "is_group": 0, "name": ("!=", exclude)},
		"name",
		order_by="creation asc",
	)
	return wh or exclude


def ensure_test_item(company: str, prefix: str = "IRR-TEST", stock_uom: str | None = None) -> str:
	item_code = f"{prefix}-{random_string(6)}"
	if frappe.db.exists("Item", item_code):
		return item_code
	props: dict = {"is_stock_item": 1}
	if stock_uom:
		props["stock_uom"] = stock_uom
	_make_item(item_code, props)
	return item_code


def fractional_uom() -> str | None:
	return frappe.db.get_value(
		"UOM", {"must_be_whole_number": 0, "enabled": 1}, "name", order_by="creation asc"
	)


def submit_stock_reconciliation_adjustment(
	company: str,
	item_code: str,
	qty: float,
	rate: float,
	warehouse: str | None = None,
):
	warehouse = warehouse or get_warehouse(company)
	return _create_stock_reconciliation(
		item_code=item_code,
		warehouse=warehouse,
		qty=qty,
		rate=rate,
		posting_date=today(),
		posting_time=nowtime(),
		purpose="Stock Reconciliation",
		company=company,
	)


def submit_material_receipt(
	company: str,
	item_code: str,
	qty: float,
	rate: float,
	warehouse: str | None = None,
):
	warehouse = warehouse or get_warehouse(company)
	se = make_stock_entry(
		item_code=item_code,
		qty=qty,
		rate=rate,
		target=warehouse,
		company=company,
		purpose="Material Receipt",
	)
	return se


def submit_opening_stock_reconciliation(
	company: str,
	item_code: str,
	qty: float,
	rate: float,
	warehouse: str | None = None,
):
	warehouse = warehouse or get_warehouse(company)
	sr = _create_stock_reconciliation(
		item_code=item_code,
		warehouse=warehouse,
		qty=qty,
		rate=rate,
		posting_date=today(),
		posting_time=nowtime(),
		purpose="Opening Stock",
		company=company,
	)
	return sr


def submit_material_transfer(
	company: str,
	item_code: str,
	qty: float,
	from_wh: str,
	to_wh: str,
):
	se = make_stock_entry(
		item_code=item_code,
		qty=qty,
		source=from_wh,
		target=to_wh,
		company=company,
		purpose="Material Transfer",
	)
	return se


def preview_stock_entry_gl(company: str, stock_entry_name: str) -> dict:
	from erpnext.controllers.stock_controller import show_accounting_ledger_preview

	return show_accounting_ledger_preview(company, "Stock Entry", stock_entry_name)


def preview_gl_totals(preview: dict) -> tuple[float, float]:
	debit = credit = 0.0
	idx_debit = idx_credit = None
	for i, col in enumerate(preview.get("gl_columns") or []):
		label = (col.get("name") or "").lower()
		if label == "debit":
			idx_debit = i
		if label == "credit":
			idx_credit = i
	for row in preview.get("gl_data") or []:
		if idx_debit is not None and len(row) > idx_debit:
			debit += flt(row[idx_debit])
		if idx_credit is not None and len(row) > idx_credit:
			credit += flt(row[idx_credit])
	return debit, credit


def voucher_ledger_snapshot(voucher_type: str, voucher_no: str):
	return fetch_gl_rows(voucher_type, voucher_no), fetch_sle_rows(voucher_type, voucher_no)


def enable_perpetual_inventory(company: str) -> None:
	if not cint(erpnext.is_perpetual_inventory_enabled(company)):
		frappe.db.set_value("Company", company, "enable_perpetual_inventory", 1)
