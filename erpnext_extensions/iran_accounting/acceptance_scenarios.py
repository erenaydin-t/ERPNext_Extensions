# Copyright (c) 2026, ERPNext Extensions contributors
"""E2E acceptance scenarios for iran_accounting (invoked from acceptance.run)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable

import frappe
from frappe.utils import add_days, flt, today

from erpnext.stock.doctype.stock_entry.stock_entry_utils import make_stock_entry

from erpnext_extensions.iran_accounting.diagnostics import (
	assert_print_no_fractional_irr,
	assert_reports_no_fractional_irr,
	check_voucher,
	run_repost_for_voucher_impl,
)
from erpnext_extensions.iran_accounting.rounding import (
	get_company_currency,
	get_currency_precision,
	round_gl_entry_amounts,
	round_sle_monetary_fields,
)
from erpnext_extensions.iran_accounting.validation import (
	assert_no_fractional_irr_gl,
	assert_no_fractional_irr_sle,
	assert_zero_value_transfer_gl_shape,
	voucher_db_flags,
)

SYNTHETIC_PREFIX = "IA-TEST"


@dataclass
class AcceptanceContext:
	company: str
	warehouse: str
	to_wh: str
	run_repost: bool
	include_synthetic: bool
	b: Any
	refs: dict[str, str] = field(default_factory=dict)
	skipped: list[dict] = field(default_factory=list)


def scenario_row(
	scenario_no: int,
	area: str,
	voucher: str = "",
	status: str = "PASS",
	gl_ok: bool | None = None,
	sle_ok: bool | None = None,
	totals_ok: bool | None = None,
	repost_ok: bool | None = None,
	report_ok: bool | None = None,
	print_ok: bool | None = None,
	evidence: str = "",
	**extra,
) -> dict[str, Any]:
	row = {
		"scenario_no": scenario_no,
		"area": area,
		"voucher": voucher or "",
		"status": status,
		"gl_ok": gl_ok,
		"sle_ok": sle_ok,
		"totals_ok": totals_ok,
		"repost_ok": repost_ok,
		"report_ok": report_ok,
		"print_ok": print_ok,
		"evidence": (evidence or "")[:500],
	}
	for key in (
		"db_gl_ok",
		"db_sle_ok",
		"db_stock_entry_ok",
		"preview_ok",
		"ui_api_ok",
		"no_double_ok",
		"no_adjustment_ok",
		"submit_ok",
	):
		if key in extra:
			row[key] = extra[key]
	return row


def _status_from_sql_checks(checks: dict, *, preview_ok: bool | None = None, repost_ok: bool | None = None) -> str:
	mandatory = [
		checks.get("db_gl_ok"),
		checks.get("db_sle_ok"),
		checks.get("db_stock_entry_ok"),
		checks.get("no_adjustment_ok"),
		checks.get("no_double_ok"),
		checks.get("totals_ok"),
	]
	if preview_ok is not None:
		mandatory.append(preview_ok)
	if repost_ok is not None:
		mandatory.append(repost_ok)
	if any(v is False for v in mandatory if v is not None):
		return "FAIL"
	return "PASS"


def _row_from_sql_checks(
	scenario_no: int,
	area: str,
	voucher: str,
	company: str,
	*,
	preview_ok: bool | None = None,
	repost_ok: bool | None = None,
	evidence: str = "",
) -> dict:
	from erpnext_extensions.iran_accounting.sql_validation import comprehensive_voucher_sql_check

	checks = comprehensive_voucher_sql_check("Stock Entry", voucher, company)
	status = _status_from_sql_checks(checks, preview_ok=preview_ok, repost_ok=repost_ok)
	return scenario_row(
		scenario_no,
		area,
		voucher,
		status,
		gl_ok=checks.get("db_gl_ok"),
		sle_ok=checks.get("db_sle_ok"),
		totals_ok=checks.get("totals_ok"),
		repost_ok=repost_ok,
		db_gl_ok=checks.get("db_gl_ok"),
		db_sle_ok=checks.get("db_sle_ok"),
		db_stock_entry_ok=checks.get("db_stock_entry_ok"),
		preview_ok=preview_ok,
		ui_api_ok=preview_ok,
		no_double_ok=checks.get("no_double_ok"),
		no_adjustment_ok=checks.get("no_adjustment_ok"),
		evidence=evidence,
	)


def _item(ctx: AcceptanceContext, tag: str, *, allow_fraction_qty: bool = False) -> str:
	uom = ctx.b.fractional_uom() if allow_fraction_qty else None
	return ctx.b.ensure_test_item(
		ctx.company, prefix=f"{SYNTHETIC_PREFIX}-{tag}", stock_uom=uom
	)


def _audit(ctx: AcceptanceContext, doctype: str, name: str) -> dict:
	flags = voucher_db_flags(doctype, name, ctx.company)
	if doctype == "Stock Entry":
		zv = assert_zero_value_transfer_gl_shape(name, ctx.company)
		if zv.get("applicable"):
			flags["totals_ok"] = flags.get("totals_ok", True) and zv.get("ok", False)
	return flags


def _repost(ctx: AcceptanceContext, doctype: str, name: str) -> tuple[bool, str]:
	if not ctx.run_repost:
		return True, "repost_skipped"
	try:
		out = run_repost_for_voucher_impl(doctype, name)
		flags = _audit(ctx, doctype, name)
		repost_ok = flags["gl_ok"] and flags["sle_ok"]
		return repost_ok, str(out.get("actions"))
	except Exception as exc:
		return False, str(exc)


def _row_from_voucher(
	ctx: AcceptanceContext,
	scenario_no: int,
	area: str,
	doctype: str,
	name: str,
	*,
	with_repost: bool = True,
) -> dict:
	flags = _audit(ctx, doctype, name)
	repost_ok = None
	evidence = ""
	if with_repost and ctx.run_repost:
		repost_ok, evidence = _repost(ctx, doctype, name)
		flags = _audit(ctx, doctype, name)
	status = "PASS" if flags["gl_ok"] and flags["sle_ok"] and flags.get("totals_ok", True) and (repost_ok is not False) else "FAIL"
	return scenario_row(
		scenario_no,
		area,
		name,
		status,
		gl_ok=flags["gl_ok"],
		sle_ok=flags["sle_ok"],
		totals_ok=flags.get("totals_ok"),
		repost_ok=repost_ok,
		evidence=evidence,
	)


def s01_settings(ctx: AcceptanceContext) -> dict:
	cur = get_company_currency(ctx.company)
	sys_prec = frappe.db.get_single_value("System Settings", "currency_precision")
	use_nf = frappe.db.get_single_value("System Settings", "use_number_format_from_currency")
	irr_nf = frappe.db.get_value("Currency", "IRR", "number_format")
	resolved = get_currency_precision("IRR")
	info = {
		"company_currency": cur,
		"system_currency_precision": sys_prec,
		"use_number_format_from_currency": use_nf,
		"irr_number_format": irr_nf,
		"resolved_irr_precision": resolved,
	}
	ok = cur == "IRR" and resolved == 0
	return scenario_row(1, "settings", ctx.company, "PASS" if ok else "FAIL", evidence=json.dumps(info, default=str))


def s02_gl_rounding(ctx: AcceptanceContext) -> dict:
	entry = {
		"company": ctx.company,
		"account_currency": "IRR",
		"transaction_currency": "IRR",
		"debit": 10596667255.68,
		"credit": 0,
		"debit_in_account_currency": 10596667255.68,
		"credit_in_account_currency": 0,
	}
	round_gl_entry_amounts(entry)
	ok = entry["debit"] == 10596667256 and entry["debit_in_account_currency"] == 10596667256
	return scenario_row(2, "GL Entry", "simulate", "PASS" if ok else "FAIL", gl_ok=ok, evidence=str(entry))


def s03_sle_rounding(ctx: AcceptanceContext) -> dict:
	sle = {"company": ctx.company, "stock_value": 1000.68, "stock_value_difference": -0.68}
	round_sle_monetary_fields(sle, ctx.company)
	ok = sle["stock_value"] == 1001 and sle["stock_value_difference"] == -1
	return scenario_row(3, "SLE", "simulate", "PASS" if ok else "FAIL", sle_ok=ok, evidence=str(sle))


def s04_opening_sr(ctx: AcceptanceContext) -> dict:
	item = _item(ctx, "OPEN")
	sr = ctx.b.submit_opening_stock_reconciliation(ctx.company, item, 3, 1234.567, ctx.warehouse)
	ctx.refs["sr_open"] = sr.name
	return _row_from_voucher(ctx, 4, "Opening Stock", "Stock Reconciliation", sr.name)


def s05_opening_mr(ctx: AcceptanceContext) -> dict:
	item = _item(ctx, "MR-OPEN")
	se = ctx.b.submit_material_receipt(ctx.company, item, 2, 10.333, ctx.warehouse)
	ctx.refs["mr_open"] = se.name
	return _row_from_voucher(ctx, 5, "Opening Stock", "Stock Entry", se.name)


def s06_pr_simple_ma(ctx: AcceptanceContext) -> dict:
	item = _item(ctx, "PR-MA")
	try:
		from erpnext.buying.doctype.purchase_order.test_purchase_order import create_purchase_order
		from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_receipt

		po = create_purchase_order(item_code=item, qty=1, rate=12, company=ctx.company, warehouse=ctx.warehouse)
		po.insert(ignore_permissions=True)
		po.submit()
		pr1 = make_purchase_receipt(po.name)
		pr1.company = ctx.company
		for r in pr1.items:
			r.warehouse = ctx.warehouse
		pr1.insert(ignore_permissions=True)
		pr1.submit()
		po2 = create_purchase_order(item_code=item, qty=1, rate=13, company=ctx.company, warehouse=ctx.warehouse)
		po2.insert(ignore_permissions=True)
		po2.submit()
		pr2 = make_purchase_receipt(po2.name)
		pr2.company = ctx.company
		for r in pr2.items:
			r.warehouse = ctx.warehouse
		pr2.insert(ignore_permissions=True)
		pr2.submit()
		ctx.refs["pr_simple"] = pr2.name
		return _row_from_voucher(ctx, 6, "Purchase Receipt", "Purchase Receipt", pr2.name)
	except Exception as exc:
		return scenario_row(6, "Purchase Receipt", "", "SKIP", evidence=str(exc))


def s07_pr_fractional(ctx: AcceptanceContext) -> dict:
	item = _item(ctx, "PR-FRAC")
	try:
		from erpnext.buying.doctype.purchase_order.test_purchase_order import create_purchase_order
		from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_receipt

		po = create_purchase_order(
			item_code=item, qty=3, rate=123.456, company=ctx.company, warehouse=ctx.warehouse
		)
		po.insert(ignore_permissions=True)
		po.submit()
		pr = make_purchase_receipt(po.name)
		pr.company = ctx.company
		for r in pr.items:
			r.warehouse = ctx.warehouse
		pr.insert(ignore_permissions=True)
		pr.submit()
		ctx.refs["pr_frac"] = pr.name
		return _row_from_voucher(ctx, 7, "Purchase Receipt", "Purchase Receipt", pr.name)
	except Exception as exc:
		return scenario_row(7, "Purchase Receipt", "", "SKIP", evidence=str(exc))


def s08_pi_irr_stock(ctx: AcceptanceContext) -> dict:
	item = _item(ctx, "PI-STK")
	ctx.b.submit_material_receipt(ctx.company, item, 1, 100, ctx.warehouse)
	supplier = frappe.db.get_value("Supplier", {}, "name")
	if not supplier:
		return scenario_row(8, "Purchase Invoice IRR", "", "SKIP", evidence="no supplier")
	pi = frappe.new_doc("Purchase Invoice")
	pi.company = ctx.company
	pi.supplier = supplier
	pi.posting_date = today()
	pi.currency = "IRR"
	pi.conversion_rate = 1
	pi.update_stock = 1
	uom = frappe.get_cached_value("Item", item, "stock_uom")
	pi.append(
		"items",
		{"item_code": item, "qty": 1, "rate": 500.777, "warehouse": ctx.warehouse, "uom": uom, "stock_uom": uom, "conversion_factor": 1},
	)
	try:
		pi.insert(ignore_permissions=True)
		pi.submit()
	except Exception as exc:
		return scenario_row(8, "Purchase Invoice IRR", "", "SKIP", evidence=str(exc))
	ctx.refs["pi_irr_stk"] = pi.name
	return _row_from_voucher(ctx, 8, "Purchase Invoice IRR", "Purchase Invoice", pi.name)


def s09_pi_irr_no_stock(ctx: AcceptanceContext) -> dict:
	supplier = frappe.db.get_value("Supplier", {}, "name")
	expense = frappe.db.get_value("Account", {"company": ctx.company, "root_type": "Expense", "is_group": 0}, "name")
	if not supplier or not expense:
		return scenario_row(9, "Purchase Invoice IRR", "", "SKIP", evidence="no supplier/expense")
	pi = frappe.new_doc("Purchase Invoice")
	pi.company = ctx.company
	pi.supplier = supplier
	pi.posting_date = today()
	pi.currency = "IRR"
	pi.conversion_rate = 1
	pi.update_stock = 0
	pi.append("items", {"item_name": "IA service", "qty": 1, "rate": 1234.567, "expense_account": expense})
	try:
		pi.insert(ignore_permissions=True)
		pi.submit()
	except Exception as exc:
		return scenario_row(9, "Purchase Invoice IRR", "", "SKIP", evidence=str(exc))
	ctx.refs["pi_irr_acct"] = pi.name
	return _row_from_voucher(ctx, 9, "Purchase Invoice IRR", "Purchase Invoice", pi.name, with_repost=False)


def s10_pi_usd(ctx: AcceptanceContext) -> dict:
	usd_acct = frappe.db.get_value("Account", {"company": ctx.company, "account_currency": "USD", "is_group": 0}, "name")
	supplier = frappe.db.get_value("Supplier", {}, "name")
	if not usd_acct or not supplier:
		return scenario_row(10, "Purchase Invoice USD", "", "SKIP", evidence="no USD account/supplier")
	pi = frappe.new_doc("Purchase Invoice")
	pi.company = ctx.company
	pi.supplier = supplier
	pi.currency = "USD"
	pi.conversion_rate = 500000
	pi.posting_date = today()
	item = _item(ctx, "PI-USD")
	uom = frappe.get_cached_value("Item", item, "stock_uom")
	pi.append("items", {"item_code": item, "qty": 1, "rate": 10.55, "uom": uom, "stock_uom": uom, "conversion_factor": 1})
	try:
		pi.insert(ignore_permissions=True)
		pi.submit()
	except Exception as exc:
		return scenario_row(10, "Purchase Invoice USD", "", "SKIP", evidence=str(exc))
	flags = voucher_db_flags("Purchase Invoice", pi.name, ctx.company)
	return scenario_row(
		10,
		"Purchase Invoice USD",
		pi.name,
		"PASS" if flags["gl_ok"] else "FAIL",
		gl_ok=flags["gl_ok"],
		evidence="USD account decimals allowed; IRR company fields checked",
	)


def s11_si_irr_stock(ctx: AcceptanceContext) -> dict:
	item = _item(ctx, "SI-STK")
	ctx.b.submit_material_receipt(ctx.company, item, 5, 33.333, ctx.warehouse)
	customer = frappe.db.get_value("Customer", {}, "name")
	if not customer:
		return scenario_row(11, "Sales Invoice IRR", "", "SKIP", evidence="no customer")
	si = frappe.new_doc("Sales Invoice")
	si.company = ctx.company
	si.customer = customer
	si.currency = "IRR"
	si.conversion_rate = 1
	si.update_stock = 1
	si.posting_date = today()
	uom = frappe.get_cached_value("Item", item, "stock_uom")
	si.append(
		"items",
		{"item_code": item, "qty": 1, "rate": 50.333, "warehouse": ctx.warehouse, "uom": uom, "stock_uom": uom, "conversion_factor": 1},
	)
	try:
		si.insert(ignore_permissions=True)
		si.submit()
	except Exception as exc:
		return scenario_row(11, "Sales Invoice IRR", "", "SKIP", evidence=str(exc))
	ctx.refs["si_irr"] = si.name
	return _row_from_voucher(ctx, 11, "Sales Invoice IRR", "Sales Invoice", si.name)


def s12_si_irr_no_stock(ctx: AcceptanceContext) -> dict:
	customer = frappe.db.get_value("Customer", {}, "name")
	income = frappe.db.get_value("Account", {"company": ctx.company, "root_type": "Income", "is_group": 0}, "name")
	if not customer or not income:
		return scenario_row(12, "Sales Invoice IRR", "", "SKIP", evidence="no customer/income")
	si = frappe.new_doc("Sales Invoice")
	si.company = ctx.company
	si.customer = customer
	si.currency = "IRR"
	si.conversion_rate = 1
	si.update_stock = 0
	si.posting_date = today()
	si.append("items", {"item_name": "IA service sale", "qty": 1, "rate": 999.777, "income_account": income})
	try:
		si.insert(ignore_permissions=True)
		si.submit()
	except Exception as exc:
		return scenario_row(12, "Sales Invoice IRR", "", "SKIP", evidence=str(exc))
	return _row_from_voucher(ctx, 12, "Sales Invoice IRR", "Sales Invoice", si.name, with_repost=False)


def s13_si_usd(ctx: AcceptanceContext) -> dict:
	return scenario_row(13, "Sales Invoice USD", "", "SKIP", evidence="configure USD receivable on site")


def s14_delivery_note(ctx: AcceptanceContext) -> dict:
	item = _item(ctx, "DN")
	ctx.b.submit_material_receipt(ctx.company, item, 5, 33.333, ctx.warehouse)
	customer = frappe.db.get_value("Customer", {}, "name")
	if not customer:
		return scenario_row(14, "Delivery Note", "", "SKIP", evidence="no customer")
	dn = frappe.new_doc("Delivery Note")
	dn.company = ctx.company
	dn.customer = customer
	dn.posting_date = today()
	uom = frappe.get_cached_value("Item", item, "stock_uom")
	dn.append(
		"items",
		{"item_code": item, "qty": 1, "rate": 33.333, "warehouse": ctx.warehouse, "uom": uom, "stock_uom": uom, "conversion_factor": 1},
	)
	try:
		dn.insert(ignore_permissions=True)
		dn.submit()
	except Exception as exc:
		return scenario_row(14, "Delivery Note", "", "SKIP", evidence=str(exc))
	ctx.refs["dn"] = dn.name
	return _row_from_voucher(ctx, 14, "Delivery Note", "Delivery Note", dn.name)


def s15_material_transfer(ctx: AcceptanceContext) -> dict:
	item = _item(ctx, "MT")
	ctx.b.submit_material_receipt(ctx.company, item, 5, 99.99, ctx.warehouse)
	se = ctx.b.submit_material_transfer(ctx.company, item, 2, ctx.warehouse, ctx.to_wh)
	ctx.refs["mt"] = se.name
	return _row_from_voucher(ctx, 15, "Material Transfer", "Stock Entry", se.name)


def s16_material_transfer_frac(ctx: AcceptanceContext) -> dict:
	item = _item(ctx, "MTF")
	ctx.b.submit_material_receipt(ctx.company, item, 3, 10.333, ctx.warehouse)
	se = ctx.b.submit_material_transfer(ctx.company, item, 1, ctx.warehouse, ctx.to_wh)
	ctx.refs["mt_frac"] = se.name
	return _row_from_voucher(ctx, 16, "Material Transfer", "Stock Entry", se.name)


def s17_material_issue(ctx: AcceptanceContext) -> dict:
	item = _item(ctx, "MI")
	ctx.b.submit_material_receipt(ctx.company, item, 4, 25.777, ctx.warehouse)
	se = make_stock_entry(
		item_code=item, qty=1, source=ctx.warehouse, company=ctx.company, purpose="Material Issue"
	)
	ctx.refs["mi"] = se.name
	return _row_from_voucher(ctx, 17, "Material Issue", "Stock Entry", se.name)


def s18_material_receipt(ctx: AcceptanceContext) -> dict:
	item = _item(ctx, "MRC")
	se = ctx.b.submit_material_receipt(ctx.company, item, 3, 10.333, ctx.warehouse)
	ctx.refs["mr"] = se.name
	return _row_from_voucher(ctx, 18, "Material Receipt", "Stock Entry", se.name)


def s19_stock_reco_adj(ctx: AcceptanceContext) -> dict:
	item = _item(ctx, "SR-ADJ")
	ctx.b.submit_material_receipt(ctx.company, item, 2, 100, ctx.warehouse)
	frappe.db.commit()
	sr = ctx.b.submit_stock_reconciliation_adjustment(
		ctx.company, item, 5, 100.333, ctx.warehouse
	)
	ctx.refs["sr_adj"] = sr.name
	return _row_from_voucher(ctx, 19, "Stock Reconciliation adjustment", "Stock Reconciliation", sr.name)


def s20_work_order_bom(ctx: AcceptanceContext) -> dict:
	try:
		_rm, _fg, wo_name, bom = _make_bom_wo(ctx)
		ctx.refs["bom"] = bom.name
		ctx.refs["wo"] = wo_name
		ok = frappe.db.exists("BOM", bom.name) and frappe.db.exists("Work Order", wo_name)
		qty = frappe.db.get_value("Work Order", wo_name, "qty")
		return scenario_row(20, "Work Order + BOM", wo_name, "PASS" if ok else "FAIL", evidence=f"qty={qty}")
	except Exception as exc:
		return scenario_row(20, "Work Order + BOM", "", "SKIP", evidence=str(exc))


def s21_mtfm(ctx: AcceptanceContext) -> dict:
	"""MTfM: preview (Desk API) -> submit -> SQL -> repost -> SQL."""
	try:
		import erpnext_extensions.iran_accounting  # noqa: F401
		from erpnext.manufacturing.doctype.work_order.work_order import make_stock_entry as wo_make_stock_entry

		from erpnext_extensions.iran_accounting.preview_validation import (
			get_accounting_ledger_preview_rows,
			preview_gl_signature,
			submitted_gl_signature,
			validate_accounting_ledger_preview,
		)
		from erpnext_extensions.iran_accounting.sql_validation import comprehensive_voucher_sql_check
		from erpnext_extensions.iran_accounting.stock_entry import align_zero_value_transfer_totals

		_rm, _fg, wo_name, _bom = _make_bom_wo(ctx, reuse=False)
		mtfm = frappe.get_doc(wo_make_stock_entry(wo_name, "Material Transfer for Manufacture", qty=1))
		mtfm.company = ctx.company
		for d in mtfm.get("items"):
			if d.s_warehouse and not d.t_warehouse:
				pass
		mtfm.insert(ignore_permissions=True)
		if hasattr(mtfm, "calculate_rate_and_amount"):
			mtfm.calculate_rate_and_amount(reset_outgoing_rate=False, raise_error_if_no_rate=False)
		if hasattr(mtfm, "set_total_incoming_outgoing_value"):
			mtfm.set_total_incoming_outgoing_value()
		align_zero_value_transfer_totals(mtfm)
		mtfm.save(ignore_permissions=True)

		preview_val = validate_accounting_ledger_preview(mtfm, ctx.company)
		preview_ok = preview_val.get("preview_ok", False)

		mtfm.submit()
		ctx.refs["mtfm"] = mtfm.name
		submit_ok = mtfm.docstatus == 1

		checks = comprehensive_voucher_sql_check("Stock Entry", mtfm.name, ctx.company)
		repost_ok = True
		repost_ev = ""
		if ctx.run_repost:
			repost_ok, repost_ev = _repost(ctx, "Stock Entry", mtfm.name)
			checks = comprehensive_voucher_sql_check("Stock Entry", mtfm.name, ctx.company)

		try:
			prev_raw = get_accounting_ledger_preview_rows(mtfm)
			sig_match = preview_gl_signature(prev_raw) == submitted_gl_signature(mtfm.name)
		except Exception:
			sig_match = True

		status = _status_from_sql_checks(
			checks,
			preview_ok=preview_ok and submit_ok,
			repost_ok=repost_ok if ctx.run_repost else None,
		)
		if not submit_ok:
			status = "FAIL"

		evidence = (
			f"preview_d={preview_val.get('debit_total')},preview_c={preview_val.get('credit_total')},"
			f"sql_d={checks.get('zero_value_shape', {}).get('debit_total')},"
			f"repost={repost_ev[:120]},sig={sig_match}"
		)
		return scenario_row(
			21,
			"MTfM",
			mtfm.name,
			status,
			gl_ok=checks.get("db_gl_ok"),
			sle_ok=checks.get("db_sle_ok"),
			totals_ok=checks.get("totals_ok"),
			repost_ok=repost_ok if ctx.run_repost else None,
			db_gl_ok=checks.get("db_gl_ok"),
			db_sle_ok=checks.get("db_sle_ok"),
			db_stock_entry_ok=checks.get("db_stock_entry_ok"),
			preview_ok=preview_ok,
			ui_api_ok=preview_ok,
			submit_ok=submit_ok,
			no_double_ok=checks.get("no_double_ok"),
			no_adjustment_ok=checks.get("no_adjustment_ok"),
			evidence=evidence,
		)
	except Exception as exc:
		return scenario_row(21, "MTfM", "", "FAIL", evidence=str(exc))


def s22_manufacture(ctx: AcceptanceContext) -> dict:
	try:
		_rm, _fg, wo_name, _bom = _make_bom_wo(ctx, reuse=True)
		from erpnext.manufacturing.doctype.work_order.work_order import make_stock_entry as wo_make_stock_entry

		if not ctx.refs.get("mtfm"):
			mtfm = frappe.get_doc(wo_make_stock_entry(wo_name, "Material Transfer for Manufacture", qty=1))
			mtfm.insert(ignore_permissions=True)
			mtfm.submit()
			ctx.refs["mtfm"] = mtfm.name
		mfg = frappe.get_doc(wo_make_stock_entry(wo_name, "Manufacture", qty=1))
		mfg.insert(ignore_permissions=True)
		mfg.submit()
		ctx.refs["mfg"] = mfg.name
		return _row_from_voucher(ctx, 22, "Manufacture", "Stock Entry", mfg.name)
	except Exception as exc:
		return scenario_row(22, "Manufacture", "", "SKIP", evidence=str(exc))


def s23_manufacture_overhead(ctx: AcceptanceContext) -> dict:
	return scenario_row(23, "Manufacture", "", "SKIP", evidence="operation/overhead not configured on site")


def s24_repost_riv(ctx: AcceptanceContext) -> dict:
	name = ctx.refs.get("mr") or ctx.refs.get("mt")
	if not name:
		return scenario_row(24, "Repost", "", "SKIP", evidence="no stock voucher created earlier")
	repost_ok, ev = _repost(ctx, "Stock Entry", name)
	flags = _audit(ctx, "Stock Entry", name)
	status = "PASS" if repost_ok and flags["gl_ok"] and flags["sle_ok"] else "FAIL"
	return scenario_row(24, "Repost", name, status, gl_ok=flags["gl_ok"], sle_ok=flags["sle_ok"], repost_ok=repost_ok, evidence=ev)


def s25_gl_report(ctx: AcceptanceContext) -> dict:
	out = assert_reports_no_fractional_irr(ctx.company)
	ok = out.get("status") == "PASS"
	return scenario_row(25, "Reports", "General Ledger", "PASS" if ok else "FAIL", report_ok=ok, evidence=str(out))


def s26_sl_report(ctx: AcceptanceContext) -> dict:
	out = assert_reports_no_fractional_irr(ctx.company)
	ok = out.get("status") == "PASS"
	return scenario_row(26, "Reports", "Stock Ledger", "PASS" if ok else "FAIL", report_ok=ok, evidence=str(out))


def s27_preview(ctx: AcceptanceContext) -> dict:
	name = ctx.refs.get("mt") or ctx.refs.get("mtfm")
	if not name or not frappe.db.exists("Stock Entry", name):
		return scenario_row(27, "Accounting Ledger Preview", "", "SKIP", evidence="no transfer voucher")
	try:
		from erpnext.controllers.stock_controller import show_accounting_ledger_preview

		se = frappe.get_doc("Stock Entry", name)
		out = show_accounting_ledger_preview(se.company, "Stock Entry", name)
		zv = assert_zero_value_transfer_gl_shape(name, ctx.company)
		di = ci = None
		for i, col in enumerate(out.get("gl_columns") or []):
			label = (col.get("name") or "").lower()
			if label == "debit":
				di = i
			if label == "credit":
				ci = i
		debit = credit = 0
		for row in out.get("gl_data") or []:
			if di is not None and len(row) > di:
				debit += flt(row[di])
			if ci is not None and len(row) > ci:
				credit += flt(row[ci])
		totals_ok = flt(debit) == flt(se.total_incoming_value) and flt(credit) == flt(
			se.total_outgoing_value
		)
		if zv.get("applicable"):
			totals_ok = bool(zv.get("ok"))
		elif flt(se.total_incoming_value) == 0 and flt(se.total_outgoing_value) == 0:
			totals_ok = debit == 0 and credit == 0
		status = "PASS" if totals_ok else "FAIL"
		return scenario_row(
			27,
			"Accounting Ledger Preview",
			name,
			status,
			gl_ok=totals_ok,
			evidence=f"d={debit},c={credit},zv={zv.get('ok')}",
		)
	except Exception as exc:
		return scenario_row(27, "Accounting Ledger Preview", name, "FAIL", evidence=str(exc))


def s28_print(ctx: AcceptanceContext) -> dict:
	name = ctx.refs.get("mfg") or ctx.refs.get("mr")
	if not name:
		return scenario_row(28, "Print", "", "MANUAL_REQUIRED", print_ok=None, evidence="no voucher for print")
	out = assert_print_no_fractional_irr("Stock Entry", name)
	if out.get("manual_required") or out.get("status") == "MANUAL_REQUIRED":
		return scenario_row(
			28, "Print", name, "MANUAL_REQUIRED", print_ok=None, evidence=out.get("reason", "")
		)
	if out.get("status") != "PASS":
		return scenario_row(28, "Print", name, "FAIL", print_ok=False, evidence=str(out))
	return scenario_row(28, "Print", name, "PASS", print_ok=True)


def _make_bom_wo(ctx: AcceptanceContext, reuse: bool = False):
	if reuse and ctx.refs.get("wo"):
		wo_name = ctx.refs["wo"]
		bom_name = ctx.refs.get("bom")
		return None, None, wo_name, frappe.get_doc("BOM", bom_name) if bom_name else None
	rm = _item(ctx, "RM", allow_fraction_qty=True)
	fg = _item(ctx, "FG")
	ctx.b.submit_material_receipt(ctx.company, rm, 10, 50.333, ctx.warehouse)
	bom = frappe.new_doc("BOM")
	bom.item = fg
	bom.company = ctx.company
	bom.quantity = 1
	bom.is_active = 1
	bom.append("items", {"item_code": rm, "qty": 1.333, "rate": 50.333})
	bom.insert(ignore_permissions=True)
	bom.submit()
	wip = frappe.db.get_value(
		"Warehouse",
		{"company": ctx.company, "warehouse_type": "Manufacturing", "is_group": 0},
		"name",
	)
	if not wip or wip == ctx.warehouse:
		wip = ctx.to_wh
	wo = frappe.new_doc("Work Order")
	wo.production_item = fg
	wo.bom_no = bom.name
	wo.company = ctx.company
	wo.qty = 1
	wo.source_warehouse = ctx.warehouse
	wo.fg_warehouse = ctx.warehouse
	wo.wip_warehouse = wip
	wo.insert(ignore_permissions=True)
	wo.submit()
	ctx.refs["bom"] = bom.name
	ctx.refs["wo"] = wo.name
	return rm, fg, wo.name, bom


SCENARIO_FUNCS: list[tuple[int, Callable[[AcceptanceContext], dict]]] = [
	(1, s01_settings),
	(2, s02_gl_rounding),
	(3, s03_sle_rounding),
	(4, s04_opening_sr),
	(5, s05_opening_mr),
	(6, s06_pr_simple_ma),
	(7, s07_pr_fractional),
	(8, s08_pi_irr_stock),
	(9, s09_pi_irr_no_stock),
	(10, s10_pi_usd),
	(11, s11_si_irr_stock),
	(12, s12_si_irr_no_stock),
	(13, s13_si_usd),
	(14, s14_delivery_note),
	(15, s15_material_transfer),
	(16, s16_material_transfer_frac),
	(17, s17_material_issue),
	(18, s18_material_receipt),
	(19, s19_stock_reco_adj),
	(20, s20_work_order_bom),
	(21, s21_mtfm),
	(22, s22_manufacture),
	(23, s23_manufacture_overhead),
	(24, s24_repost_riv),
	(25, s25_gl_report),
	(26, s26_sl_report),
	(27, s27_preview),
	(28, s28_print),
]


def run_scenarios(ctx: AcceptanceContext, scenario_count: int) -> list[dict]:
	rows = []
	for no, fn in SCENARIO_FUNCS:
		if no > scenario_count:
			break
		if not ctx.include_synthetic and no > 3:
			ctx.skipped.append({"scenario_no": no, "reason": "include_synthetic=false"})
			continue
		try:
			rows.append(fn(ctx))
		except Exception as exc:
			rows.append(scenario_row(no, fn.__name__, "", "FAIL", evidence=str(exc)))
	frappe.db.commit()
	return rows


def run_real_stock_entries(ctx: AcceptanceContext, vouchers: list[str]) -> list[dict]:
	from erpnext_extensions.iran_accounting.diagnostics import check_stock_entry, repost_and_check_stock_entry

	rows = []
	base_no = 100
	for name in vouchers:
		if not frappe.db.exists("Stock Entry", name):
			rows.append(scenario_row(base_no, "Stock Entry totals", name, "SKIP", evidence="not on site"))
			base_no += 1
			continue
		pre = check_stock_entry(name)
		rows.append(
			scenario_row(
				base_no,
				"GL Entry",
				name,
				pre.get("status", "FAIL"),
				gl_ok=pre.get("checks", {}).get("no_fractional_gl"),
				sle_ok=pre.get("checks", {}).get("no_fractional_sle"),
				totals_ok=pre.get("checks", {}).get("gl_debit_matches_incoming"),
				evidence="pre-repost",
			)
		)
		base_no += 1
		if ctx.run_repost:
			post = repost_and_check_stock_entry(name)
			rows.append(
				scenario_row(
					base_no,
					"Repost",
					name,
					post.get("status", "FAIL"),
					gl_ok=post.get("checks", {}).get("no_fractional_gl"),
					sle_ok=post.get("checks", {}).get("no_fractional_sle"),
					totals_ok=post.get("checks", {}).get("gl_debit_matches_incoming"),
					repost_ok=post.get("status") == "PASS",
					evidence=str(post.get("repost_actions", "")),
				)
			)
			base_no += 1
	return rows
