# Copyright (c) 2026, ERPNext Extensions contributors
"""Whitelisted helpers for Playwright E2E (Scenario 21 MTfM)."""

from __future__ import annotations

import frappe
from frappe.utils import flt

from erpnext_extensions.iran_accounting.preview_validation import validate_accounting_ledger_preview
from erpnext_extensions.iran_accounting.sql_validation import (
	comprehensive_voucher_sql_check,
	sql_get_gl_rows,
	sql_get_stock_entry_rows,
	sql_gl_grouped_totals,
)


@frappe.whitelist()
def resolve_mtfm_stock_entry(company=None, stock_entry=None, create_if_missing=True):
	"""Return an MTfM Stock Entry name (prefer draft for preview UI)."""
	frappe.set_user("Administrator")
	company = company or frappe.db.get_value("Company", {"default_currency": "IRR"}, "name")
	if stock_entry and frappe.db.exists("Stock Entry", stock_entry):
		doc = frappe.get_doc("Stock Entry", stock_entry)
		if doc.purpose != "Material Transfer for Manufacture":
			frappe.throw(f"{stock_entry} is not Material Transfer for Manufacture")
		return _context_from_doc(doc)

	if stock_entry:
		frappe.throw(f"Stock Entry {stock_entry} not found")

	name = frappe.db.get_value(
		"Stock Entry",
		{"company": company, "purpose": "Material Transfer for Manufacture", "docstatus": 0},
		"name",
		order_by="modified desc",
	)
	if name:
		return _context_from_doc(frappe.get_doc("Stock Entry", name))

	create = create_if_missing
	if isinstance(create, str):
		create = bool(int(create)) if create.isdigit() else frappe.parse_json(create)
	if create:
		return _create_mtfm_draft(company)

	name = frappe.db.get_value(
		"Stock Entry",
		{"company": company, "purpose": "Material Transfer for Manufacture", "docstatus": 1},
		"name",
		order_by="modified desc",
	)
	if name:
		return _context_from_doc(frappe.get_doc("Stock Entry", name))

	frappe.throw("No MTfM Stock Entry on site; set E2E_MTFM_STOCK_ENTRY or enable create_if_missing")


def _create_mtfm_draft(company: str) -> dict:
	from erpnext.manufacturing.doctype.work_order.work_order import make_stock_entry as wo_make_stock_entry

	import erpnext_extensions.iran_accounting  # noqa: F401
	from erpnext_extensions.iran_accounting import e2e_bootstrap as b
	from erpnext_extensions.iran_accounting.acceptance_scenarios import AcceptanceContext, _make_bom_wo
	from erpnext_extensions.iran_accounting.stock_entry import align_zero_value_transfer_totals

	b.enable_perpetual_inventory(company)
	wh = b.get_warehouse(company)
	to_wh = b.get_second_warehouse(company, wh)
	ctx = AcceptanceContext(
		company=company,
		warehouse=wh,
		to_wh=to_wh,
		run_repost=False,
		include_synthetic=True,
		b=b,
	)
	_rm, _fg, wo_name, _bom = _make_bom_wo(ctx, reuse=False)
	mtfm = frappe.get_doc(wo_make_stock_entry(wo_name, "Material Transfer for Manufacture", qty=1))
	mtfm.company = company
	mtfm.insert(ignore_permissions=True)
	if hasattr(mtfm, "set_total_incoming_outgoing_value"):
		mtfm.set_total_incoming_outgoing_value()
	align_zero_value_transfer_totals(mtfm)
	mtfm.save(ignore_permissions=True)
	frappe.db.commit()
	return _context_from_doc(mtfm)


def _context_from_doc(doc) -> dict:
	items = doc.get("items") or []
	source_wh = target_wh = None
	for row in items:
		if row.s_warehouse:
			source_wh = source_wh or row.s_warehouse
		if row.t_warehouse:
			target_wh = target_wh or row.t_warehouse
	return {
		"stock_entry": doc.name,
		"company": doc.company,
		"docstatus": doc.docstatus,
		"purpose": doc.purpose,
		"source_warehouse": source_wh,
		"target_warehouse": target_wh,
		"total_incoming_value": flt(doc.total_incoming_value),
		"total_outgoing_value": flt(doc.total_outgoing_value),
		"value_difference": flt(doc.value_difference),
		"desk_url": f"/desk/stock-entry/{doc.name}",
	}


@frappe.whitelist()
def validate_stock_entry_gl_sql(stock_entry: str):
	"""SQL-backed GL validation for Playwright post-submit checks."""
	frappe.set_user("Administrator")
	if not frappe.db.exists("Stock Entry", stock_entry):
		frappe.throw(f"Stock Entry {stock_entry} not found")
	company = frappe.db.get_value("Stock Entry", stock_entry, "company")
	checks = comprehensive_voucher_sql_check("Stock Entry", stock_entry, company)
	grouped = sql_gl_grouped_totals(stock_entry)
	header = sql_get_stock_entry_rows(stock_entry).get("header") or {}
	gl_rows = sql_get_gl_rows("Stock Entry", stock_entry)
	debit = flt(grouped.get("debit"))
	credit = flt(grouped.get("credit"))
	expected_in = flt(header.get("total_incoming_value"))
	return {
		"checks": checks,
		"gl_row_count": len(gl_rows),
		"sum_debit": debit,
		"sum_credit": credit,
		"total_incoming_value": expected_in,
		"debit_equals_credit": debit == credit,
		"debit_equals_incoming": debit == expected_in,
		"not_doubled": debit <= expected_in + 0.01 if expected_in else True,
		"status": "PASS"
		if checks.get("db_gl_ok")
		and checks.get("totals_ok")
		and checks.get("no_adjustment_ok")
		and checks.get("no_double_ok")
		and debit == credit
		else "FAIL",
	}


@frappe.whitelist()
def validate_preview_api(stock_entry: str):
	"""Server-side preview validation (same logic as acceptance; no db rollback)."""
	frappe.set_user("Administrator")
	doc = frappe.get_doc("Stock Entry", stock_entry)
	return validate_accounting_ledger_preview(doc, doc.company)
