# Copyright (c) 2026, ERPNext Extensions contributors
"""Hard reset + Stock Reconciliation regression from empty inventory (IRR)."""

from __future__ import annotations

from typing import Any

import frappe
from erpnext.stock.doctype.stock_entry.stock_entry_utils import make_stock_entry
from frappe.utils import flt, nowtime, random_string, today

from erpnext_extensions.iran_accounting.domain.currency import round_row_amount_financial
from erpnext_extensions.iran_accounting.domain.qty_rate_amount import (
	sum_stock_reconciliation_amount_difference,
	sum_stock_reconciliation_row_amounts,
)
from erpnext_extensions.iran_accounting.e2e_bootstrap import (
	enable_perpetual_inventory,
	ensure_test_item,
	fractional_uom,
	get_irr_company,
	get_warehouse,
)
from erpnext_extensions.iran_accounting.qty_rate_consistency import (
	_gl_stock_totals,
	_sle_value_diff_sum,
	check_qty_rate_amount_consistency,
)
from erpnext_extensions.iran_accounting.rounding import amount_is_fractional, get_company_currency

CLEAN_SLATE_PREFIX = "IA-CLEANSLATE-"

DEFAULT_TEST_PREFIXES = (
	CLEAN_SLATE_PREFIX,
	"IA-SR-",
	"IA-TEST-SR-",
	"IA-HARD-",
	"IA-SR-E2E",
	"IRR-TEST",
	"IRR-OPEN",
)


def _items_for_prefixes(company: str, prefixes: tuple[str, ...]) -> list[str]:
	if not prefixes:
		return []
	clauses = " or ".join(["item_code like %s"] * len(prefixes))
	params = [f"{p}%%" for p in prefixes]
	return frappe.db.sql_list(
		f"""
		select name from `tabItem`
		where is_stock_item=1 and ({clauses})
		""",
		params,
	)


def _sql_in_clause(values: list) -> tuple[str, list]:
	if not values:
		return "1=0", []
	placeholders = ", ".join(["%s"] * len(values))
	return f"({placeholders})", list(values)


def _voucher_names_for_items(
	company: str, item_codes: list[str], doctype: str, child_table: str
) -> list[str]:
	if not item_codes:
		return []
	in_sql, in_vals = _sql_in_clause(item_codes)
	return frappe.db.sql_list(
		f"""
		select distinct parent from `tab{child_table}`
		where item_code in {in_sql}
		""",
		in_vals,
	)


def _stock_vouchers_for_items(company: str, item_codes: list[str]) -> dict[str, list[str]]:
	if not item_codes:
		return {}
	in_sql, in_vals = _sql_in_clause(item_codes)
	rows = frappe.db.sql(
		f"""
		select distinct voucher_type, voucher_no
		from `tabStock Ledger Entry`
		where company=%s and item_code in {in_sql}
		""",
		[company, *in_vals],
		as_dict=True,
	)
	out: dict[str, list[str]] = {}
	for r in rows:
		out.setdefault(r.voucher_type, []).append(r.voucher_no)
	for k in out:
		out[k] = sorted(set(out[k]))
	return out


def _cancel_and_delete_voucher(doctype: str, name: str) -> None:
	if not frappe.db.exists(doctype, name):
		return
	doc = frappe.get_doc(doctype, name)
	doc.flags.ignore_permissions = True
	if doc.docstatus == 1:
		try:
			doc.cancel()
		except Exception:
			frappe.db.rollback()
			doc = frappe.get_doc(doctype, name)
			doc.flags.ignore_permissions = True
			if doc.docstatus == 1:
				raise
	if doc.docstatus in (0, 2):
		frappe.delete_doc(doctype, name, force=1, ignore_permissions=True)


def _zero_bins(item_codes: list[str], company: str) -> None:
	if not item_codes:
		return
	wh_names = frappe.db.sql_list(
		"select name from `tabWarehouse` where company=%s and is_group=0",
		company,
	)
	for item in item_codes:
		for wh in wh_names:
			if not frappe.db.exists("Bin", {"item_code": item, "warehouse": wh}):
				continue
			frappe.db.set_value(
				"Bin",
				{"item_code": item, "warehouse": wh},
				{
					"actual_qty": 0,
					"stock_value": 0,
					"valuation_rate": 0,
					"reserved_qty": 0,
					"ordered_qty": 0,
					"indented_qty": 0,
					"projected_qty": 0,
				},
			)


def _clear_repost_logs(company: str, item_codes: list[str]) -> None:
	for dt in ("Repost Item Valuation", "Repost Accounting Ledger"):
		if not frappe.db.exists("DocType", dt):
			continue
		filters: dict = {"company": company}
		if item_codes and frappe.db.has_column(dt, "item_code"):
			for name in frappe.db.get_all(dt, filters=filters, pluck="name"):
				doc = frappe.get_doc(dt, name)
				if getattr(doc, "item_code", None) and doc.item_code not in item_codes:
					continue
				try:
					frappe.delete_doc(dt, name, force=1, ignore_permissions=True)
				except Exception:
					pass
		else:
			frappe.db.delete(dt, filters)


def hard_reset_test_stock_data(
	company: str,
	*,
	item_prefixes: tuple[str, ...] = DEFAULT_TEST_PREFIXES,
) -> dict[str, Any]:
	"""Remove test vouchers, zero bins, clear repost logs (masters untouched)."""
	from erpnext_extensions.iran_accounting.integration.bootstrap import apply

	apply()
	frappe.set_user("Administrator")

	item_codes = _items_for_prefixes(company, item_prefixes)
	deleted: dict[str, list[str]] = {"Stock Reconciliation": [], "Stock Entry": []}

	for doctype, child in (
		("Stock Reconciliation", "Stock Reconciliation Item"),
		("Stock Entry", "Stock Entry Detail"),
	):
		for name in _voucher_names_for_items(company, item_codes, doctype, child):
			try:
				_cancel_and_delete_voucher(doctype, name)
				deleted[doctype].append(name)
			except Exception as exc:
				frappe.log_error(title=f"clean_slate delete {doctype} {name}", message=str(exc))

	extra = _stock_vouchers_for_items(company, item_codes)
	for name in extra.get("Stock Reconciliation", []):
		if name not in deleted["Stock Reconciliation"]:
			try:
				_cancel_and_delete_voucher("Stock Reconciliation", name)
				deleted["Stock Reconciliation"].append(name)
			except Exception:
				pass
	for name in extra.get("Stock Entry", []):
		if name not in deleted["Stock Entry"]:
			try:
				_cancel_and_delete_voucher("Stock Entry", name)
				deleted["Stock Entry"].append(name)
			except Exception:
				pass

	_zero_bins(item_codes, company)
	_clear_repost_logs(company, item_codes)
	frappe.db.commit()

	return {
		"company": company,
		"item_codes": item_codes,
		"deleted": deleted,
		"item_prefixes": item_prefixes,
	}


def _make_clean_item(company: str, tag: str, *, has_batch: bool = False, stock_uom: str | None = None) -> str:
	uom = stock_uom
	if not uom and not has_batch:
		uom = None
	code = ensure_test_item(company, prefix=f"{CLEAN_SLATE_PREFIX}{tag}", stock_uom=uom)
	if has_batch:
		frappe.db.set_value("Item", code, "has_batch_no", 1, update_modified=False)
	return code


def _ensure_batch(item_code: str) -> str:
	batch_id = f"CS-{random_string(6)}"
	b = frappe.get_doc({"doctype": "Batch", "item": item_code, "batch_id": batch_id})
	b.insert(ignore_permissions=True)
	return b.name


def _assert_bin_empty(item_code: str, warehouse: str) -> None:
	row = frappe.db.get_value(
		"Bin",
		{"item_code": item_code, "warehouse": warehouse},
		["actual_qty", "stock_value"],
		as_dict=True,
	)
	if not row:
		return
	if flt(row.actual_qty) or flt(row.stock_value):
		frappe.throw(f"Bin not empty for {item_code}: qty={row.actual_qty} value={row.stock_value}")


def _material_receipt(company: str, item: str, warehouse: str, qty: float, rate: float):
	se = make_stock_entry(
		item_code=item,
		qty=qty,
		target=warehouse,
		rate=rate,
		company=company,
		purpose="Material Receipt",
	)
	se.submit()
	return se


def _submit_opening_sr(
	company: str,
	warehouse: str,
	item_code: str,
	qty: float,
	valuation_rate: float,
	*,
	batch_no: str | None = None,
) -> frappe.model.document.Document:
	sr = frappe.new_doc("Stock Reconciliation")
	sr.purpose = "Opening Stock"
	sr.company = company
	sr.posting_date = today()
	sr.posting_time = nowtime()
	sr.set_posting_time = 1
	sr.expense_account = frappe.get_cached_value(
		"Company", company, "temporary_opening_account"
	) or frappe.db.get_value(
		"Account",
		{"company": company, "account_type": "Temporary", "is_group": 0},
		"name",
	)
	sr.cost_center = frappe.get_cached_value("Company", company, "cost_center")
	sr.difference_account = sr.expense_account
	row: dict = {
		"item_code": item_code,
		"warehouse": warehouse,
		"qty": qty,
		"valuation_rate": valuation_rate,
		"current_qty": 0,
		"current_valuation_rate": 0,
		"reconcile_all_serial_batch": 1,
	}
	if batch_no:
		row["batch_no"] = batch_no
	sr.append("items", row)
	sr.insert(ignore_permissions=True)
	sr.submit()
	return sr


def _submit_mixed_sr(
	company: str,
	warehouse: str,
	rows: list[dict],
) -> frappe.model.document.Document:
	sr = frappe.new_doc("Stock Reconciliation")
	sr.purpose = "Stock Reconciliation"
	sr.company = company
	sr.posting_date = today()
	sr.posting_time = nowtime()
	sr.set_posting_time = 1
	sr.expense_account = frappe.get_cached_value(
		"Company", company, "stock_adjustment_account"
	) or frappe.db.get_value("Account", {"account_type": "Stock Adjustment", "company": company}, "name")
	sr.cost_center = frappe.get_cached_value("Company", company, "cost_center")
	for row in rows:
		sr.append(
			"items",
			{
				"item_code": row["item_code"],
				"warehouse": warehouse,
				"qty": row["qty"],
				"valuation_rate": row["valuation_rate"],
				"current_qty": row.get("current_qty", 0),
				"current_valuation_rate": row.get("current_valuation_rate", 0),
				"reconcile_all_serial_batch": 1,
				**({"batch_no": row["batch_no"]} if row.get("batch_no") else {}),
			},
		)
	sr.insert(ignore_permissions=True)
	sr.submit()
	return sr


def assert_stock_reconciliation_voucher(voucher_no: str, company: str) -> dict[str, Any]:
	"""Row/header/GL/SLE checks; returns PASS/FAIL breakdown."""
	ccy = get_company_currency(company)
	doc = frappe.get_doc("Stock Reconciliation", voucher_no)
	header = flt(doc.difference_amount)
	net = sum_stock_reconciliation_amount_difference(doc)
	gross = sum_stock_reconciliation_row_amounts(doc)
	gl = _gl_stock_totals("Stock Reconciliation", voucher_no)
	gl_mag = max(flt(gl.get("debit")), flt(gl.get("credit")))
	sle_sum = flt(_sle_value_diff_sum("Stock Reconciliation", voucher_no))

	failures: list[str] = []
	row_breakdown: list[dict] = []

	for item in doc.items:
		exp_amt = float(round_row_amount_financial(item.qty, item.valuation_rate, ccy))
		exp_diff = flt(item.amount) - flt(item.current_amount)
		if flt(item.amount) != exp_amt:
			failures.append(f"row {item.idx}: amount {item.amount} != round(qty×rate) {exp_amt}")
		if flt(item.amount_difference) != flt(item.amount) - flt(item.current_amount):
			failures.append(
				f"row {item.idx}: amount_difference {item.amount_difference} "
				f"!= amount-current {flt(item.amount) - flt(item.current_amount)}"
			)
		for label, val in (("amount", item.amount), ("amount_difference", item.amount_difference)):
			if amount_is_fractional(val, ccy):
				failures.append(f"row {item.idx}: fractional IRR {label}={val}")
		row_breakdown.append(
			{
				"idx": item.idx,
				"item_code": item.item_code,
				"qty": flt(item.qty),
				"rate": flt(item.valuation_rate),
				"amount": flt(item.amount),
				"current_amount": flt(item.current_amount),
				"amount_difference": flt(item.amount_difference),
				"expected_amount": exp_amt,
			}
		)

	if header != net:
		failures.append(f"header {header} != SUM(amount_difference) {net}")
	if gross != net and header == gross:
		failures.append(f"gross mode: header {header} == SUM(amount) {gross}")
	if doc.docstatus == 1:
		if abs(header) != gl_mag:
			failures.append(f"GL magnitude {gl_mag} != |header| {abs(header)}")
		if abs(header) != abs(sle_sum):
			failures.append(f"SLE sum {sle_sum} != header {header}")

	chk = check_qty_rate_amount_consistency("Stock Reconciliation", voucher_no, company)
	if chk.get("status") != "PASS":
		failures.extend(chk.get("consistency_failures") or [])

	status = "PASS" if not failures else "FAIL"
	return {
		"voucher_no": voucher_no,
		"status": status,
		"header": header,
		"sum_amount_difference": net,
		"sum_amount_gross": gross,
		"gl_magnitude": gl_mag,
		"sle_sum": sle_sum,
		"row_breakdown": row_breakdown,
		"failures": failures,
		"mismatch_irr": failures[0] if failures else None,
	}


def _snapshot_system_settings() -> dict:
	ss = frappe.get_single("System Settings")
	return {
		"currency_precision": ss.get("currency_precision"),
		"float_precision": ss.get("float_precision"),
		"use_number_format_from_currency": cint_safe(ss.get("use_number_format_from_currency")),
	}


def cint_safe(v):
	try:
		return int(v) if v not in (None, "") else None
	except (TypeError, ValueError):
		return None


def _apply_system_settings(**kwargs) -> None:
	ss = frappe.get_single("System Settings")
	for k, v in kwargs.items():
		ss.set(k, v)
	ss.save(ignore_permissions=True)
	frappe.db.commit()
	frappe.clear_cache()


def run_clean_slate_regression(
	company: str | None = None,
	*,
	item_prefixes: tuple[str, ...] = DEFAULT_TEST_PREFIXES,
) -> dict[str, Any]:
	"""Full reset → controlled SRs → assertions → system settings sweep."""
	from erpnext_extensions.iran_accounting.integration.bootstrap import apply

	apply()
	frappe.set_user("Administrator")
	company = company or get_irr_company("ESPAD")
	enable_perpetual_inventory(company)
	warehouse = get_warehouse(company)
	ccy = get_company_currency(company)

	reset_out = hard_reset_test_stock_data(company, item_prefixes=item_prefixes)
	vouchers: list[dict] = []

	item_plain = _make_clean_item(company, "PLAIN")
	item_batch = _make_clean_item(company, "BATCH", has_batch=True)
	frac_uom = fractional_uom()
	item_frac = _make_clean_item(company, "FRAC", stock_uom=frac_uom) if frac_uom else item_plain

	for code in (item_plain, item_batch, item_frac):
		_assert_bin_empty(code, warehouse)

	# CASE A — Opening 3 × 9877
	sr_a = _submit_opening_sr(company, warehouse, item_plain, 3, 9877)
	frappe.db.commit()
	res_a = assert_stock_reconciliation_voucher(sr_a.name, company)
	res_a["case"] = "A_opening_9877"
	res_a["expected_header"] = 29631
	if flt(res_a["header"]) != 29631:
		res_a["status"] = "FAIL"
		res_a.setdefault("failures", []).append(
			f"regression 9877: header {res_a['header']} != expected 29631"
		)
	vouchers.append(res_a)

	# CASE A batch item
	batch_no = _ensure_batch(item_batch)
	sr_batch = _submit_opening_sr(company, warehouse, item_batch, 2, 5000, batch_no=batch_no)
	frappe.db.commit()
	res_batch = assert_stock_reconciliation_voucher(sr_batch.name, company)
	res_batch["case"] = "A_batch_opening"
	vouchers.append(res_batch)

	# CASE B — mixed reconciliation (three items / three rows)
	item_mix_a = _make_clean_item(company, "MIX-A")
	item_mix_b = _make_clean_item(company, "MIX-B")
	item_mix_c = (
		_make_clean_item(company, "MIX-C", stock_uom=frac_uom)
		if frac_uom
		else _make_clean_item(company, "MIX-C")
	)
	_material_receipt(company, item_mix_b, warehouse, 5, 2000)
	frappe.db.commit()

	mixed_rows = [
		{
			"item_code": item_mix_a,
			"qty": 5,
			"valuation_rate": 1111,
			"current_qty": 0,
			"current_valuation_rate": 0,
		},
		{
			"item_code": item_mix_b,
			"qty": 2,
			"valuation_rate": 1500,
			"current_qty": 5,
			"current_valuation_rate": 2000,
		},
	]
	if frac_uom:
		mixed_rows.append(
			{
				"item_code": item_mix_c,
				"qty": 1.5,
				"valuation_rate": 4000,
				"current_qty": 0,
				"current_valuation_rate": 0,
			}
		)
	else:
		mixed_rows.append(
			{
				"item_code": item_mix_c,
				"qty": 1,
				"valuation_rate": 3500,
				"current_qty": 0,
				"current_valuation_rate": 0,
			}
		)

	sr_b = _submit_mixed_sr(company, warehouse, mixed_rows)
	frappe.db.commit()
	res_b = assert_stock_reconciliation_voucher(sr_b.name, company)
	res_b["case"] = "B_mixed"
	vouchers.append(res_b)

	# System settings sweep — 9877 case must stay 29631
	settings_snap = _snapshot_system_settings()
	settings_cases: list[dict] = []
	for label, overrides in (
		("null_currency_precision", {"currency_precision": None, "float_precision": 7}),
		("float_precision_7", {"float_precision": 7}),
		("toggle_number_format", {"use_number_format_from_currency": 1}),
	):
		try:
			_apply_system_settings(**overrides)
			item_ss = _make_clean_item(company, f"SS-{label}")
			_assert_bin_empty(item_ss, warehouse)
			sr_ss = _submit_opening_sr(company, warehouse, item_ss, 3, 9877)
			frappe.db.commit()
			hdr = flt(frappe.db.get_value("Stock Reconciliation", sr_ss.name, "difference_amount"))
			ok = hdr == 29631
			settings_cases.append(
				{"label": label, "header": hdr, "expected": 29631, "status": "PASS" if ok else "FAIL"}
			)
			if not ok:
				res_a["status"] = "FAIL"
				res_a.setdefault("failures", []).append(f"system settings {label}: header {hdr}")
		finally:
			pass

	if settings_snap:
		_apply_system_settings(**{k: v for k, v in settings_snap.items() if v is not None})

	overall = (
		"PASS"
		if all(v["status"] == "PASS" for v in vouchers) and all(s["status"] == "PASS" for s in settings_cases)
		else "FAIL"
	)

	return {
		"overall": overall,
		"company": company,
		"currency": ccy,
		"reset": reset_out,
		"vouchers": vouchers,
		"system_settings_sweep": settings_cases,
	}


@frappe.whitelist()
def run_clean_slate_regression_api(company: str | None = None):
	return run_clean_slate_regression(company=company)
