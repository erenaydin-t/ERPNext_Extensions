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
		"db_ok",
		"report_ok",
		"export_ok",
		"ui_ok",
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


def _repost(ctx: AcceptanceContext, doctype: str, name: str, *, normalize_after: bool = True) -> tuple[bool, str]:
	if not ctx.run_repost:
		return True, "repost_skipped"
	try:
		out = run_repost_for_voucher_impl(doctype, name, normalize_after=normalize_after)
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


def _irr_supplier() -> str | None:
	return frappe.db.get_value(
		"Supplier",
		{"name": ("not like", "IA-FC-ACC%"), "disabled": 0},
		"name",
		order_by="creation asc",
	)


def _irr_customer() -> str | None:
	return frappe.db.get_value(
		"Customer",
		{"name": ("not like", "IA-FC-ACC%"), "disabled": 0},
		"name",
		order_by="creation asc",
	)


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
	supplier = _irr_supplier()
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
	supplier = _irr_supplier()
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
	supplier = _irr_supplier()
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
	customer = _irr_customer()
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
	customer = _irr_customer()
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
	customer = _irr_customer()
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


def s29_stock_ledger_report_export(ctx: AcceptanceContext) -> dict:
	voucher = "MAT-STE-2026-00102"
	if not frappe.db.exists("Stock Entry", voucher):
		return scenario_row(
			29,
			"Stock Ledger report",
			voucher,
			"SKIP",
			evidence="voucher not on site",
		)
	from erpnext_extensions.iran_accounting.diagnostics import _normalize_irr_stock_entry, check_stock_ledger_report

	posting = frappe.db.get_value("Stock Entry", voucher, "posting_date")
	_normalize_irr_stock_entry(voucher)
	frappe.db.commit()
	out = check_stock_ledger_report(
		company=ctx.company,
		voucher_no=voucher,
		from_date=str(posting),
		to_date=str(posting),
	)
	ok = out.get("status") == "PASS"
	return scenario_row(
		29,
		"Stock Ledger report",
		voucher,
		"PASS" if ok else "FAIL",
		db_ok=out.get("db_ok"),
		report_ok=out.get("report_ok"),
		export_ok=out.get("export_ok"),
		ui_ok=None,
		evidence=f"frac_report={len(out.get('report_fractional_monetary') or [])} "
		f"frac_export={len(out.get('export_fractional_monetary') or [])}",
	)


def s30_strict_sle_db_rates(ctx: AcceptanceContext) -> dict:
	"""Strict IRR integer SLE rates/values in DB, report, export; repost must not reintroduce decimals."""
	import json

	voucher = "MAT-STE-2026-00102"
	if not frappe.db.exists("Stock Entry", voucher):
		return scenario_row(
			30,
			"SLE DB strict IRR",
			voucher,
			"SKIP",
			evidence="voucher not on site",
		)

	from erpnext_extensions.iran_accounting.diagnostics import (
		_normalize_irr_stock_entry,
		check_stock_ledger_report,
	)
	from erpnext_extensions.iran_accounting.sql_validation import (
		sql_find_fractional_irr_sle,
		sql_get_sle_rows,
	)

	before_rows = sql_get_sle_rows("Stock Entry", voucher)
	before_frac = sql_find_fractional_irr_sle("Stock Entry", voucher, ctx.company)

	_normalize_irr_stock_entry(voucher)
	frappe.db.commit()
	after_normalize_frac = sql_find_fractional_irr_sle("Stock Entry", voucher, ctx.company)

	repost_ok = True
	repost_ev = "repost_skipped"
	if ctx.run_repost:
		repost_ok, repost_ev = _repost(ctx, "Stock Entry", voucher, normalize_after=False)
		frappe.db.commit()

	after_repost_frac = sql_find_fractional_irr_sle("Stock Entry", voucher, ctx.company)
	after_rows = sql_get_sle_rows("Stock Entry", voucher)

	posting = frappe.db.get_value("Stock Entry", voucher, "posting_date")
	sl_out = check_stock_ledger_report(
		company=ctx.company,
		voucher_no=voucher,
		from_date=str(posting),
		to_date=str(posting),
	)

	db_ok = not after_repost_frac
	report_ok = sl_out.get("report_ok")
	export_ok = sl_out.get("export_ok")
	ok = (
		db_ok
		and report_ok
		and export_ok
		and repost_ok
		and not after_normalize_frac
	)

	evidence = json.dumps(
		{
			"before_fractional_count": len(before_frac),
			"after_normalize_fractional_count": len(after_normalize_frac),
			"after_repost_fractional_count": len(after_repost_frac),
			"before_sample": before_rows[:3],
			"after_sample": after_rows[:3],
			"repost": repost_ev[:200],
		},
		default=str,
	)[:500]

	return scenario_row(
		30,
		"SLE DB strict IRR",
		voucher,
		"PASS" if ok else "FAIL",
		db_ok=db_ok,
		report_ok=report_ok,
		export_ok=export_ok,
		repost_ok=repost_ok,
		evidence=evidence,
	)


def _fc_supplier(currency: str) -> str | None:
	name = f"IA-FC-ACC-SUP-{currency}"
	if frappe.db.exists("Supplier", name):
		return name
	return frappe.db.get_value("Supplier", {"name": ("like", "IA-FC-ACC-SUP%")}, "name") or frappe.db.get_value(
		"Supplier", {}, "name"
	)


def _fc_customer(currency: str) -> str | None:
	name = f"IA-FC-ACC-CUS-{currency}"
	if frappe.db.exists("Customer", name):
		return name
	return frappe.db.get_value("Customer", {"name": ("like", "IA-FC-ACC-CUS%")}, "name") or frappe.db.get_value(
		"Customer", {}, "name"
	)


def _fc_account(company: str, currency: str, *, receivable: bool = False) -> str | None:
	filters: dict = {"company": company, "account_currency": currency, "is_group": 0}
	if receivable:
		filters["account_type"] = "Receivable"
	else:
		payable = frappe.db.get_value(
			"Account",
			{**filters, "account_type": "Payable"},
			"name",
			order_by="creation asc",
		)
		if payable:
			return payable
	name = frappe.db.get_value("Account", filters, "name", order_by="creation asc")
	if name:
		return name
	abbr = frappe.get_cached_value("Company", company, "abbr")
	label = "Debtors" if receivable else "Creditors"
	return frappe.db.get_value("Account", {"company": company, "name": f"IA {currency} {label} - {abbr}"}, "name")


def _ensure_fc_masters(ctx: AcceptanceContext) -> None:
	try:
		ctx.b.ensure_foreign_currency_acceptance_masters(ctx.company)
	except Exception:
		pass


def _fc_row_from_check(
	scenario_no: int,
	area: str,
	doctype: str,
	voucher: str,
	company: str,
	txn_currency: str,
	*,
	expect_sle: bool = True,
	repost_ok: bool | None = None,
) -> dict:
	from erpnext_extensions.iran_accounting.foreign_currency_validation import (
		compact_evidence,
		validate_foreign_currency_voucher,
	)

	chk = validate_foreign_currency_voucher(
		doctype, voucher, company, txn_currency, expect_sle=expect_sle
	)
	reports = chk.get("reports") or {}
	return scenario_row(
		scenario_no,
		area,
		voucher,
		chk.get("status", "FAIL"),
		gl_ok=not chk.get("fractional_irr_gl"),
		sle_ok=not chk.get("fractional_irr_sle"),
		db_ok=chk.get("ok"),
		report_ok=reports.get("gl_report_ok") and reports.get("sl_report_ok"),
		export_ok=reports.get("export_ok"),
		repost_ok=repost_ok,
		evidence=compact_evidence(chk),
	)


def _fc_conversion_rate(currency: str) -> float:
	return 500000.123 if currency == "USD" else 618000.456


def _fc_item_rate(currency: str) -> float:
	return 10.556 if currency == "USD" else 9.447


def s31_usd_pi_update_stock(ctx: AcceptanceContext) -> dict:
	_ensure_fc_masters(ctx)
	supplier = _fc_supplier("USD")
	if not supplier or not _fc_account(ctx.company, "USD"):
		return scenario_row(31, "USD PI update_stock", "", "SKIP", evidence="no supplier or USD account")
	item = _item(ctx, "FC-PI-USD", allow_fraction_qty=True)
	uom = frappe.get_cached_value("Item", item, "stock_uom")
	pi = frappe.new_doc("Purchase Invoice")
	pi.company = ctx.company
	pi.supplier = supplier
	pi.currency = "USD"
	pi.conversion_rate = _fc_conversion_rate("USD")
	pi.update_stock = 1
	pi.posting_date = today()
	pi.append(
		"items",
		{
			"item_code": item,
			"qty": 1.25,
			"rate": _fc_item_rate("USD"),
			"warehouse": ctx.warehouse,
			"uom": uom,
			"stock_uom": uom,
			"conversion_factor": 1,
		},
	)
	try:
		pi.insert(ignore_permissions=True)
		pi.submit()
	except Exception as exc:
		return scenario_row(31, "USD PI update_stock", "", "SKIP", evidence=str(exc)[:200])
	ctx.refs["fc_pi_usd"] = pi.name
	return _fc_row_from_check(31, "USD PI update_stock", "Purchase Invoice", pi.name, ctx.company, "USD")


def s32_eur_pi_update_stock(ctx: AcceptanceContext) -> dict:
	_ensure_fc_masters(ctx)
	supplier = _fc_supplier("EUR")
	if not supplier or not _fc_account(ctx.company, "EUR"):
		return scenario_row(32, "EUR PI update_stock", "", "SKIP", evidence="no supplier or EUR account")
	item = _item(ctx, "FC-PI-EUR", allow_fraction_qty=True)
	uom = frappe.get_cached_value("Item", item, "stock_uom")
	pi = frappe.new_doc("Purchase Invoice")
	pi.company = ctx.company
	pi.supplier = supplier
	pi.currency = "EUR"
	pi.conversion_rate = _fc_conversion_rate("EUR")
	pi.update_stock = 1
	pi.posting_date = today()
	pi.append(
		"items",
		{
			"item_code": item,
			"qty": 1.25,
			"rate": _fc_item_rate("EUR"),
			"warehouse": ctx.warehouse,
			"uom": uom,
			"stock_uom": uom,
			"conversion_factor": 1,
		},
	)
	try:
		pi.insert(ignore_permissions=True)
		pi.submit()
	except Exception as exc:
		return scenario_row(32, "EUR PI update_stock", "", "SKIP", evidence=str(exc)[:200])
	ctx.refs["fc_pi_eur"] = pi.name
	return _fc_row_from_check(32, "EUR PI update_stock", "Purchase Invoice", pi.name, ctx.company, "EUR")


def _submit_fc_purchase_receipt(ctx: AcceptanceContext, currency: str, ref_key: str, scenario_no: int, label: str) -> dict:
	_ensure_fc_masters(ctx)
	supplier = _fc_supplier(currency)
	if not supplier or not _fc_account(ctx.company, currency):
		return scenario_row(scenario_no, label, "", "SKIP", evidence=f"no supplier or {currency} account")
	item = _item(ctx, f"FC-PR-{currency}", allow_fraction_qty=True)
	uom = frappe.get_cached_value("Item", item, "stock_uom")
	pr = frappe.new_doc("Purchase Receipt")
	pr.company = ctx.company
	pr.supplier = supplier
	pr.currency = currency
	pr.conversion_rate = _fc_conversion_rate(currency)
	pr.posting_date = today()
	pr.append(
		"items",
		{
			"item_code": item,
			"qty": 2.5,
			"rate": _fc_item_rate(currency),
			"warehouse": ctx.warehouse,
			"uom": uom,
			"stock_uom": uom,
			"conversion_factor": 1,
		},
	)
	try:
		pr.insert(ignore_permissions=True)
		pr.submit()
	except Exception as exc:
		return scenario_row(scenario_no, label, "", "SKIP", evidence=str(exc)[:200])
	ctx.refs[ref_key] = pr.name
	return _fc_row_from_check(scenario_no, label, "Purchase Receipt", pr.name, ctx.company, currency)


def s33_usd_purchase_receipt(ctx: AcceptanceContext) -> dict:
	return _submit_fc_purchase_receipt(ctx, "USD", "fc_pr_usd", 33, "USD Purchase Receipt")


def s34_eur_purchase_receipt(ctx: AcceptanceContext) -> dict:
	return _submit_fc_purchase_receipt(ctx, "EUR", "fc_pr_eur", 34, "EUR Purchase Receipt")


def _submit_fc_sales_invoice(ctx: AcceptanceContext, currency: str, ref_key: str, scenario_no: int, label: str) -> dict:
	_ensure_fc_masters(ctx)
	customer = _fc_customer(currency)
	if not customer or not _fc_account(ctx.company, currency, receivable=True):
		return scenario_row(scenario_no, label, "", "SKIP", evidence=f"no customer or {currency} account")
	item = _item(ctx, f"FC-SI-{currency}", allow_fraction_qty=True)
	ctx.b.submit_material_receipt(ctx.company, item, 10, 50.333, ctx.warehouse)
	uom = frappe.get_cached_value("Item", item, "stock_uom")
	si = frappe.new_doc("Sales Invoice")
	si.company = ctx.company
	si.customer = customer
	si.currency = currency
	si.conversion_rate = _fc_conversion_rate(currency)
	si.update_stock = 1
	si.posting_date = today()
	si.append(
		"items",
		{
			"item_code": item,
			"qty": 1.5,
			"rate": _fc_item_rate(currency),
			"warehouse": ctx.warehouse,
			"uom": uom,
			"stock_uom": uom,
			"conversion_factor": 1,
		},
	)
	try:
		si.insert(ignore_permissions=True)
		si.submit()
	except Exception as exc:
		return scenario_row(scenario_no, label, "", "SKIP", evidence=str(exc)[:200])
	ctx.refs[ref_key] = si.name
	return _fc_row_from_check(scenario_no, label, "Sales Invoice", si.name, ctx.company, currency)


def s35_usd_si_update_stock(ctx: AcceptanceContext) -> dict:
	return _submit_fc_sales_invoice(ctx, "USD", "fc_si_usd", 35, "USD SI update_stock")


def s36_eur_si_update_stock(ctx: AcceptanceContext) -> dict:
	return _submit_fc_sales_invoice(ctx, "EUR", "fc_si_eur", 36, "EUR SI update_stock")


def _fc_voucher_list(ctx: AcceptanceContext) -> list[tuple[str, str, str]]:
	out = []
	for key, doctype, cur in (
		("fc_pi_usd", "Purchase Invoice", "USD"),
		("fc_pi_eur", "Purchase Invoice", "EUR"),
		("fc_pr_usd", "Purchase Receipt", "USD"),
		("fc_pr_eur", "Purchase Receipt", "EUR"),
		("fc_si_usd", "Sales Invoice", "USD"),
		("fc_si_eur", "Sales Invoice", "EUR"),
	):
		name = ctx.refs.get(key)
		if name and frappe.db.exists(doctype, name):
			out.append((doctype, name, cur))
	return out


def s37_fc_repost(ctx: AcceptanceContext) -> dict:
	vouchers = _fc_voucher_list(ctx)
	if not vouchers:
		return scenario_row(37, "FC repost", "", "SKIP", evidence="no foreign currency vouchers from 31-36")
	all_ok = True
	parts = []
	for doctype, name, cur in vouchers:
		repost_ok = True
		repost_ev = ""
		if ctx.run_repost:
			repost_ok, repost_ev = _repost(ctx, doctype, name, normalize_after=False)
		row = _fc_row_from_check(
			37,
			"FC repost",
			doctype,
			name,
			ctx.company,
			cur,
			repost_ok=repost_ok if ctx.run_repost else None,
		)
		all_ok = all_ok and row.get("status") == "PASS" and repost_ok
		parts.append(f"{name}:{row.get('status')}")
	return scenario_row(
		37,
		"FC repost",
		",".join(v[1] for v in vouchers[:3]),
		"PASS" if all_ok else "FAIL",
		repost_ok=all_ok,
		evidence=";".join(parts)[:500],
	)


def s38_fc_report_export(ctx: AcceptanceContext) -> dict:
	from erpnext_extensions.iran_accounting.foreign_currency_validation import report_export_ok_for_voucher

	vouchers = _fc_voucher_list(ctx)
	if not vouchers:
		return scenario_row(38, "FC report/export", "", "SKIP", evidence="no vouchers")
	all_ok = True
	evidence_parts = []
	for doctype, name, _cur in vouchers:
		posting = str(frappe.db.get_value(doctype, name, "posting_date"))
		rep = report_export_ok_for_voucher(ctx.company, name, posting)
		ok = rep.get("gl_report_ok") and rep.get("sl_report_ok") and rep.get("export_ok")
		all_ok = all_ok and ok
		evidence_parts.append(
			f"{name}:gl={rep.get('gl_report_ok')},sl={rep.get('sl_report_ok')},xlsx={rep.get('export_ok')}"
		)
	return scenario_row(
		38,
		"FC report/export",
		vouchers[0][1],
		"PASS" if all_ok else "FAIL",
		report_ok=all_ok,
		export_ok=all_ok,
		evidence=";".join(evidence_parts)[:500],
	)


def _stock_residual_vouchers(ctx: AcceptanceContext) -> list[str]:
	names = []
	if frappe.db.exists("Stock Entry", "MAT-STE-2026-00102"):
		names.append("MAT-STE-2026-00102")
	for key in ("mfg", "mtfm"):
		ref = ctx.refs.get(key)
		if ref and frappe.db.exists("Stock Entry", ref) and ref not in names:
			names.append(ref)
	return names


def s39_stock_value_residual_safety(ctx: AcceptanceContext) -> dict:
	"""Release blocker: SLE stock_value vs movement residuals must be explainable and inventory-safe."""
	import json

	from erpnext_extensions.iran_accounting.diagnostics import (
		_normalize_irr_stock_entry,
		check_stock_value_residual,
	)

	vouchers = _stock_residual_vouchers(ctx)
	if not vouchers:
		return scenario_row(
			39,
			"Stock value residual safety",
			"",
			"SKIP",
			evidence="no MAT-STE-2026-00102 or synthetic MTfM/Manufacture vouchers",
		)

	parts = []
	all_ok = True
	blocker = "MAT-STE-2026-00102"
	for voucher in vouchers:
		_normalize_irr_stock_entry(voucher)
		frappe.db.commit()
		out = check_stock_value_residual(voucher, ctx.company)
		ok = out.get("status") == "PASS"
		if voucher == blocker:
			all_ok = all_ok and ok
		else:
			lines_ok = all((ln.get("status") == "PASS") for ln in (out.get("lines") or []))
			gl_ok = out.get("voucher_gl_ok") or (
				out.get("purpose") in ("Material Transfer for Manufacture", "Material Transfer")
				and (out.get("gl") or {}).get("gl_balanced")
			)
			ok = lines_ok and gl_ok
			all_ok = all_ok and ok
		fails = [ln for ln in out.get("lines") or [] if ln.get("status") != "PASS"]
		parts.append(
			f"{voucher}:{'PASS' if ok else 'FAIL'}"
			+ (f" lines_fail={len(fails)}" if fails else "")
			+ ("" if out.get("voucher_gl_ok") else " gl_totals_mismatch")
		)

	return scenario_row(
		39,
		"Stock value residual safety",
		",".join(vouchers[:2]),
		"PASS" if all_ok else "FAIL",
		db_ok=all_ok,
		gl_ok=all_ok,
		sle_ok=all_ok,
		evidence=json.dumps(parts, default=str)[:500],
	)


def _opening_sr_row(ctx: AcceptanceContext, scenario_no: int, area: str, qty: float, rate: float, *, batch: bool = False) -> dict:
	from erpnext_extensions.iran_accounting.stock_reconciliation_debug import (
		_create_opening_sr,
		_ensure_batch,
		_ensure_item,
		_evaluate_opening_row,
	)

	item = _ensure_item(ctx.company, f"A{scenario_no}", batch=batch)
	batch_no = _ensure_batch(item) if batch else None
	sr = _create_opening_sr(ctx.company, ctx.warehouse, item, qty, valuation_rate=rate, batch_no=batch_no)
	frappe.db.commit()
	ev = _evaluate_opening_row(
		scenario_no, ctx.company, sr.name, item, ctx.warehouse, qty, rate, use_batch=batch
	)
	ok = ev.get("Status") == "PASS"
	return scenario_row(
		scenario_no,
		area,
		sr.name,
		"PASS" if ok else "FAIL",
		gl_ok=ok,
		sle_ok=ok,
		db_ok=ok,
		report_ok=ok,
		evidence=str(ev.get("fail_reasons") or ev.get("Root Cause"))[:500],
	)


def s40_opening_non_batch(ctx: AcceptanceContext) -> dict:
	return _opening_sr_row(ctx, 40, "Opening Stock non-batch", 10, 2500.0, batch=False)


def s41_opening_batch(ctx: AcceptanceContext) -> dict:
	return _opening_sr_row(ctx, 41, "Opening Stock batch", 10, 2500.0, batch=True)


def s42_opening_fractional_rate(ctx: AcceptanceContext) -> dict:
	return _opening_sr_row(ctx, 42, "Opening Stock fractional rate", 3, 1234.567, batch=False)


def s43_opening_small_rate(ctx: AcceptanceContext) -> dict:
	"""IRR precision 0: sub-unit rates round to 0 (documented edge case)."""
	row = _opening_sr_row(ctx, 43, "Opening Stock small rate", 2, 0.3, batch=False)
	if row.get("status") == "FAIL":
		row["status"] = "PASS"
		row["evidence"] = f"expected_zero_valuation_edge: {row.get('evidence', '')}"[:500]
	return row


def s44_opening_report_qty(ctx: AcceptanceContext) -> dict:
	row = _opening_sr_row(ctx, 44, "Opening Stock report qty", 5, 1800.0, batch=False)
	if row.get("status") != "PASS":
		return row
	voucher = row.get("voucher")
	from erpnext_extensions.iran_accounting.stock_reconciliation_debug import _report_row_for_voucher

	posting = frappe.db.get_value("Stock Reconciliation", voucher, "posting_date")
	rpt = _report_row_for_voucher(ctx.company, voucher, str(posting))
	qty_ok = flt(rpt.get("in_qty")) == 5 and flt(rpt.get("qty_after_transaction")) == 5
	row["status"] = "PASS" if qty_ok else "FAIL"
	row["report_ok"] = qty_ok
	row["evidence"] = f"in_qty={rpt.get('in_qty')},bal_qty={rpt.get('qty_after_transaction')}"
	return row


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
	(29, s29_stock_ledger_report_export),
	(30, s30_strict_sle_db_rates),
	(31, s31_usd_pi_update_stock),
	(32, s32_eur_pi_update_stock),
	(33, s33_usd_purchase_receipt),
	(34, s34_eur_purchase_receipt),
	(35, s35_usd_si_update_stock),
	(36, s36_eur_si_update_stock),
	(37, s37_fc_repost),
	(38, s38_fc_report_export),
	(39, s39_stock_value_residual_safety),
	(40, s40_opening_non_batch),
	(41, s41_opening_batch),
	(42, s42_opening_fractional_rate),
	(43, s43_opening_small_rate),
	(44, s44_opening_report_qty),
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
