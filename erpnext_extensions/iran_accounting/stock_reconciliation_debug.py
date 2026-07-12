# Copyright (c) 2026, ERPNext Extensions contributors
"""Opening Stock Reconciliation investigation helpers."""

from __future__ import annotations

from typing import Any

import frappe
from frappe.utils import flt, nowtime, random_string, today

from erpnext_extensions.iran_accounting.reports import (
	run_stock_ledger_report,
	stock_ledger_report_monetary_fields,
)
from erpnext_extensions.iran_accounting.rounding import (
	amount_is_fractional,
	get_company_currency,
	is_irr_company,
)
from erpnext_extensions.iran_accounting.stock_ledger_report import (
	default_stock_ledger_filters,
	monetary_fieldnames_from_columns,
)


def _print_matrix(rows: list[dict]) -> None:
	headers = (
		"Scenario",
		"Item",
		"Batch",
		"In Qty",
		"In Rate",
		"Voucher",
		"SRI Qty",
		"SRI Rate",
		"SLE Act",
		"SLE QtyAfter",
		"SLE InRate",
		"SLE ValRate",
		"Bin Qty",
		"Bin Rate",
		"Rpt In",
		"Rpt Out",
		"Rpt BalQty",
		"Rpt InRate",
		"Rpt ValRate",
		"Rpt OutRate",
		"Rpt BalVal",
		"SLE OutRate",
		"Status",
		"Root Cause",
	)
	widths = [4, 18, 6, 6, 8, 18, 6, 8, 6, 8, 8, 8, 6, 8, 6, 6, 8, 8, 8, 8, 8, 8, 6, 24]
	line = " | ".join(h.ljust(widths[i])[: widths[i]] for i, h in enumerate(headers))
	print(line)
	print("-" * len(line))
	for r in rows:
		print(" | ".join(str(r.get(h, "")).ljust(widths[i])[: widths[i]] for i, h in enumerate(headers)))


def _create_opening_sr(
	company: str,
	warehouse: str,
	item_code: str,
	qty: float,
	*,
	valuation_rate: float | None = None,
	amount: float | None = None,
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
	row = {
		"item_code": item_code,
		"warehouse": warehouse,
		"qty": qty,
		"reconcile_all_serial_batch": 1,
	}
	if batch_no:
		row["batch_no"] = batch_no
	if amount is not None:
		row["amount"] = amount
		if qty:
			row["valuation_rate"] = flt(amount) / flt(qty)
	else:
		row["valuation_rate"] = valuation_rate
	sr.append("items", row)
	sr.insert(ignore_permissions=True)
	sr.submit()
	return sr


def _ensure_item(company: str, tag: str, *, batch: bool = False) -> str:
	from erpnext_extensions.iran_accounting.e2e_bootstrap import ensure_test_item

	item = ensure_test_item(company, prefix=f"IA-TEST-SR-{tag}")
	if batch:
		frappe.db.set_value("Item", item, "has_batch_no", 1, update_modified=False)
	return item


def _ensure_batch(item_code: str) -> str:
	batch_id = f"IA-B-{random_string(6)}"
	b = frappe.get_doc({"doctype": "Batch", "item": item_code, "batch_id": batch_id})
	b.insert(ignore_permissions=True)
	return b.name


def _report_row_for_voucher(company: str, voucher_no: str, posting_date: str) -> dict:
	filters = default_stock_ledger_filters(
		company, voucher_no=voucher_no, from_date=posting_date, to_date=posting_date
	)
	columns, data = run_stock_ledger_report(filters)
	monetary = tuple(stock_ledger_report_monetary_fields(columns, filters))
	for row in data or []:
		if isinstance(row, dict) and row.get("voucher_no") == voucher_no:
			return {**row, "_monetary_fields": monetary, "_columns": columns}
	return {}


def _evaluate_opening_row(
	scenario_no: int,
	company: str,
	voucher_no: str,
	item_code: str,
	warehouse: str,
	input_qty: float,
	input_rate: float,
	*,
	use_batch: bool,
) -> dict[str, Any]:
	currency = get_company_currency(company)
	sri = frappe.db.sql(
		"""
		select qty, valuation_rate, amount, batch_no
		from `tabStock Reconciliation Item` where parent=%s and item_code=%s limit 1
		""",
		(voucher_no, item_code),
		as_dict=True,
	)
	sri = sri[0] if sri else {}
	sle = frappe.db.sql(
		"""
		select actual_qty, qty_after_transaction, incoming_rate, outgoing_rate, valuation_rate,
		       stock_value, stock_value_difference
		from `tabStock Ledger Entry`
		where voucher_type='Stock Reconciliation' and voucher_no=%s and item_code=%s
		order by creation desc limit 1
		""",
		(voucher_no, item_code),
		as_dict=True,
	)
	sle = sle[0] if sle else {}
	bin_row = frappe.db.get_value(
		"Bin",
		{"item_code": item_code, "warehouse": warehouse},
		["actual_qty", "valuation_rate", "stock_value"],
		as_dict=True,
	)
	posting = frappe.db.get_value("Stock Reconciliation", voucher_no, "posting_date")
	report = _report_row_for_voucher(company, voucher_no, str(posting)) if posting else {}

	fail_reasons: list[str] = []
	qty_in = flt(input_qty)
	rate_in = flt(input_rate)
	if qty_in > 0 and rate_in > 0:
		checks = [
			(flt(sle.get("qty_after_transaction")) > 0, "SLE qty_after_transaction"),
			(flt(sle.get("valuation_rate")) > 0, "SLE valuation_rate"),
			(flt(sle.get("incoming_rate")) > 0, "SLE incoming_rate"),
			(flt(sle.get("outgoing_rate")) == 0, "SLE outgoing_rate must be 0 on positive opening"),
			(flt(sle.get("stock_value")) > 0, "SLE stock_value"),
			(flt((bin_row or {}).get("actual_qty")) > 0, "Bin qty"),
			(flt((bin_row or {}).get("valuation_rate")) > 0, "Bin valuation_rate"),
			(flt((bin_row or {}).get("stock_value")) > 0, "Bin stock_value"),
			(flt(report.get("in_qty")) > 0, "Report in_qty"),
			(flt(report.get("qty_after_transaction")) > 0, "Report balance qty"),
			(flt(report.get("incoming_rate")) > 0, "Report incoming_rate"),
			(flt(report.get("valuation_rate")) > 0, "Report valuation_rate"),
			(
				flt(report.get("in_out_rate")) == 0,
				"Report outgoing rate (in_out_rate) must be 0 on positive opening",
			),
			(flt(report.get("stock_value")) > 0, "Report balance value"),
		]
		for ok, label in checks:
			if not ok:
				fail_reasons.append(label)
		if flt(sle.get("actual_qty")) == 0 and flt(sle.get("qty_after_transaction")) > 0:
			if flt(report.get("in_qty")) == 0:
				fail_reasons.append("Report in_qty vs qty_after (opening)")

		for field in ("stock_value", "valuation_rate", "incoming_rate", "stock_value_difference"):
			val = sle.get(field)
			if val not in (None, "") and amount_is_fractional(val, currency):
				fail_reasons.append(f"Fractional IRR SLE {field}")

	status = "PASS" if not fail_reasons else "FAIL"
	root = ""
	if fail_reasons:
		if rate_in > 0 and rate_in < 1 and flt(sle.get("valuation_rate")) == 0:
			root = "IRR integer precision rounds sub-unit rate to 0 (expected policy)"
		elif flt(sle.get("valuation_rate")) == 0 and flt(sri.get("valuation_rate")) > 0:
			root = "SLE valuation zeroed before stock_value (iran_accounting reconcile on before_insert)"
		else:
			root = "; ".join(fail_reasons[:3])
	else:
		root = "OK"

	return {
		"Scenario": scenario_no,
		"Item": item_code,
		"Batch": "Y" if use_batch else "N",
		"In Qty": qty_in,
		"In Rate": rate_in,
		"Voucher": voucher_no,
		"SRI Qty": sri.get("qty"),
		"SRI Rate": sri.get("valuation_rate"),
		"SLE Act": sle.get("actual_qty"),
		"SLE QtyAfter": sle.get("qty_after_transaction"),
		"SLE InRate": sle.get("incoming_rate"),
		"SLE ValRate": sle.get("valuation_rate"),
		"SLE StockValue": sle.get("stock_value"),
		"Bin Qty": (bin_row or {}).get("actual_qty"),
		"Bin Rate": (bin_row or {}).get("valuation_rate"),
		"Rpt In": report.get("in_qty"),
		"Rpt Out": report.get("out_qty"),
		"Rpt BalQty": report.get("qty_after_transaction"),
		"Rpt InRate": report.get("incoming_rate"),
		"Rpt ValRate": report.get("valuation_rate"),
		"Rpt OutRate": report.get("in_out_rate"),
		"Rpt BalVal": report.get("stock_value"),
		"SLE OutRate": sle.get("outgoing_rate"),
		"Status": status,
		"Root Cause": root,
		"fail_reasons": fail_reasons,
		"gl": frappe.db.sql(
			"""
			select account, debit, credit from `tabGL Entry`
			where voucher_type='Stock Reconciliation' and voucher_no=%s and is_cancelled=0
			""",
			voucher_no,
			as_dict=True,
		),
	}


def _ensure_batch_stock_settings() -> None:
	"""Batch opening rows require serial/batch bundle support on this ERPNext version."""
	meta = frappe.get_meta("Stock Settings")
	for fieldname in (
		"enable_serial_and_batch_no_for_item",
		"use_serial_batch_fields",
	):
		if meta.has_field(fieldname):
			frappe.db.set_single_value("Stock Settings", fieldname, 1)


def run_opening_stock_matrix(company: str) -> list[dict]:
	import erpnext_extensions.iran_accounting  # noqa: F401 — patches
	from erpnext_extensions.iran_accounting.e2e_bootstrap import enable_perpetual_inventory, get_warehouse

	if not is_irr_company(company):
		frappe.throw(f"Company {company} is not IRR")
	enable_perpetual_inventory(company)
	_ensure_batch_stock_settings()
	warehouse = get_warehouse(company)

	specs = [
		(1, False, 10, 2500.0, None, "qty+rate non-batch"),
		(2, True, 10, 2500.0, None, "qty+rate batch"),
		(3, False, 8, None, 20000.0, "qty+amount non-batch"),
		(4, True, 8, None, 20000.0, "qty+amount batch"),
		(5, False, 3, 1234.567, None, "fractional rate non-batch"),
		(6, True, 3, 1234.567, None, "fractional rate batch"),
		(7, False, 2, 0.3, None, "small rate non-batch"),
		(8, True, 2, 0.3, None, "small rate batch"),
	]

	rows: list[dict] = []
	for scenario_no, use_batch, qty, rate, amount, _label in specs:
		item = _ensure_item(company, f"S{scenario_no}", batch=use_batch)
		batch_no = _ensure_batch(item) if use_batch else None
		if rate is not None and amount is None:
			sr = _create_opening_sr(company, warehouse, item, qty, valuation_rate=rate, batch_no=batch_no)
			input_rate = rate
		else:
			sr = _create_opening_sr(company, warehouse, item, qty, amount=amount, batch_no=batch_no)
			input_rate = flt(amount) / flt(qty) if qty else 0
		frappe.db.commit()
		rows.append(
			_evaluate_opening_row(
				scenario_no,
				company,
				sr.name,
				item,
				warehouse,
				qty,
				input_rate,
				use_batch=use_batch,
			)
		)
	return rows
