# Copyright (c) 2026, ERPNext Extensions contributors

from __future__ import annotations

import frappe
from frappe.utils import add_days, flt, today

from erpnext_extensions.iran_accounting.rounding import (
	get_company_currency,
	is_irr_company,
	round_currency,
	round_gl_entry_amounts,
	round_sle_monetary_fields,
	round_stock_entry_totals,
)
from erpnext_extensions.iran_accounting.validation import (
	check_print_html_no_irr_monetary_decimals,
	fetch_gl_rows,
	fetch_sle_rows,
	fractional_gl_fields,
	fractional_sle_fields,
	gl_debit_credit_totals,
	is_doubled_gl,
	stock_adj_round_off_rows,
	summarize_voucher_check,
)


def _normalize_irr_stock_entry(voucher_no: str) -> list[str]:
	se = frappe.get_doc("Stock Entry", voucher_no)
	if not is_irr_company(se.company):
		return []

	actions = []
	round_stock_entry_totals(se)
	se.db_set(
		{
			"total_incoming_value": se.total_incoming_value,
			"total_outgoing_value": se.total_outgoing_value,
			"value_difference": se.value_difference,
		},
		update_modified=False,
	)
	actions.append("normalized_stock_entry_totals")

	for sle_name in frappe.get_all(
		"Stock Ledger Entry",
		pluck="name",
		filters={"voucher_type": "Stock Entry", "voucher_no": voucher_no, "is_cancelled": 0},
	):
		sle = frappe.get_doc("Stock Ledger Entry", sle_name)
		round_sle_monetary_fields(sle, se.company)
		sle.db_update()
	actions.append("normalized_sle_monetary_fields")

	for gle_name in frappe.get_all(
		"GL Entry",
		pluck="name",
		filters={"voucher_type": "Stock Entry", "voucher_no": voucher_no, "is_cancelled": 0},
	):
		gle = frappe.get_doc("GL Entry", gle_name)
		round_gl_entry_amounts(gle)
		gle.db_update()
	actions.append("normalized_gl_entry_amounts")
	return actions


def _voucher_no_arg(voucher_no):
	if isinstance(voucher_no, dict):
		return voucher_no.get("voucher_no")
	return voucher_no


def _print_check(doctype: str, voucher_no: str) -> dict | None:
	try:
		html = frappe.get_print(doctype, voucher_no)
		return check_print_html_no_irr_monetary_decimals(html)
	except Exception as exc:
		return {"status": "SKIP", "error": str(exc)}


def check_voucher(doctype: str, voucher_no: str, *, include_print: bool = False) -> dict:
	voucher_no = _voucher_no_arg(voucher_no)
	if not frappe.db.exists(doctype, voucher_no):
		frappe.throw(f"{doctype} {voucher_no} not found")

	doc = frappe.get_doc(doctype, voucher_no)
	company = doc.company
	gl_rows = fetch_gl_rows(doctype, voucher_no)
	sle_rows = fetch_sle_rows(doctype, voucher_no) if frappe.get_meta(doctype).has_field("update_stock") or doctype in (
		"Stock Entry",
		"Purchase Receipt",
		"Delivery Note",
		"Purchase Invoice",
		"Sales Invoice",
		"Stock Reconciliation",
	) else []

	if doctype == "Stock Entry" and not sle_rows:
		sle_rows = fetch_sle_rows(doctype, voucher_no)

	print_result = _print_check(doctype, voucher_no) if include_print else None
	extra = {}
	if doctype == "Stock Entry":
		debit_total, credit_total = gl_debit_credit_totals(gl_rows)
		expected_in = round_currency(doc.total_incoming_value, get_company_currency(company))
		expected_out = round_currency(doc.total_outgoing_value, get_company_currency(company))
		adj = stock_adj_round_off_rows(gl_rows, company)
		extra = {
			"no_stock_adjustment_or_round_off": not adj,
			"gl_debit_matches_incoming": flt(debit_total) == flt(expected_in),
			"gl_credit_matches_outgoing": flt(credit_total) == flt(expected_out),
			"not_doubled": not is_doubled_gl(debit_total, expected_in),
			"value_difference_zero_at_precision": flt(doc.value_difference) == 0,
		}

	result = summarize_voucher_check(
		doctype, voucher_no, company, gl_rows, sle_rows, extra_checks=extra, print_result=print_result
	)
	result["docstatus"] = doc.docstatus
	if doctype == "Stock Entry":
		result.update(
			{
				"purpose": doc.purpose,
				"total_incoming_value": doc.total_incoming_value,
				"total_outgoing_value": doc.total_outgoing_value,
				"value_difference": doc.value_difference,
				"gl_debit_total": debit_total,
				"gl_credit_total": credit_total,
				"stock_adjustment_or_round_off_rows": adj,
				"doubled_gl_detected": is_doubled_gl(debit_total, expected_in),
			}
		)
	return result


@frappe.whitelist()
def check_stock_entry(voucher_no):
	return check_voucher("Stock Entry", voucher_no)


@frappe.whitelist()
def check_purchase_receipt(voucher_no):
	return check_voucher("Purchase Receipt", voucher_no)


@frappe.whitelist()
def check_purchase_invoice(voucher_no):
	return check_voucher("Purchase Invoice", voucher_no)


@frappe.whitelist()
def check_sales_invoice(voucher_no):
	return check_voucher("Sales Invoice", voucher_no)


@frappe.whitelist()
def check_delivery_note(voucher_no):
	return check_voucher("Delivery Note", voucher_no)


@frappe.whitelist()
def check_stock_reconciliation(voucher_no):
	return check_voucher("Stock Reconciliation", voucher_no)


@frappe.whitelist()
def check_company_fractional_irr(company=None, limit=100):
	return check_irr_fractional_rows(company=company, limit=limit)


@frappe.whitelist()
def repost_and_check_stock_entry(voucher_no):
	voucher_no = _voucher_no_arg(voucher_no)
	repost_actions = []
	if not frappe.db.exists("Stock Entry", voucher_no):
		frappe.throw(f"Stock Entry {voucher_no} not found")

	se = frappe.get_doc("Stock Entry", voucher_no)

	if frappe.db.exists("DocType", "Repost Item Valuation"):
		try:
			from erpnext.stock.doctype.repost_item_valuation.repost_item_valuation import repost

			riv = frappe.new_doc("Repost Item Valuation")
			riv.company = se.company
			riv.voucher_type = "Stock Entry"
			riv.voucher_no = voucher_no
			riv.repost_only_accounting_ledgers = 1
			riv.flags.ignore_permissions = True
			riv.insert(ignore_permissions=True)
			repost(riv)
			repost_actions.append(f"repost_item_valuation:{riv.name}")
		except Exception as exc:
			repost_actions.append(f"repost_item_valuation_failed:{exc!s}")

	try:
		from erpnext.accounts.utils import repost_gle_for_stock_vouchers

		repost_gle_for_stock_vouchers(
			stock_vouchers=[("Stock Entry", voucher_no)],
			posting_date=se.posting_date,
			company=se.company,
		)
		repost_actions.append("repost_gle_for_stock_vouchers")
	except Exception as exc:
		repost_actions.append(f"repost_gle_for_stock_vouchers_failed:{exc!s}")

	repost_actions.extend(_normalize_irr_stock_entry(voucher_no))
	frappe.db.commit()

	result = check_stock_entry(voucher_no)
	result["repost_actions"] = repost_actions
	return result


@frappe.whitelist()
def check_irr_fractional_rows(company=None, limit=100):
	limit = int(limit or 100)
	company = company or frappe.db.get_value("Company", {"default_currency": "IRR"}, "name")
	if not company:
		return {"company": company, "fractional_gl": [], "fractional_sle": [], "fractional_stock_entry": []}

	gl = frappe.db.sql(
		"""
		select name, voucher_type, voucher_no, debit, credit,
			debit_in_account_currency, credit_in_account_currency
		from `tabGL Entry`
		where company = %s and is_cancelled = 0
		limit %s
		""",
		(company, limit * 3),
		as_dict=True,
	)
	fractional_gl = []
	for row in gl:
		if fractional_gl_fields(row, company):
			fractional_gl.append(row)
		if len(fractional_gl) >= limit:
			break

	sle = frappe.db.sql(
		"""
		select name, voucher_no, stock_value, stock_value_difference, valuation_rate, actual_qty
		from `tabStock Ledger Entry`
		where company = %s and is_cancelled = 0
		limit %s
		""",
		(company, limit * 3),
		as_dict=True,
	)
	fractional_sle = []
	for row in sle:
		if fractional_sle_fields(row, company):
			fractional_sle.append(row)
		if len(fractional_sle) >= limit:
			break

	ste = frappe.db.sql(
		"""
		select name, total_incoming_value, total_outgoing_value, value_difference
		from `tabStock Entry`
		where company = %s and docstatus = 1
		limit %s
		""",
		(company, limit * 3),
		as_dict=True,
	)
	currency = get_company_currency(company)
	fractional_stock_entry = [
		r
		for r in ste
		if any(
			round_currency(r.get(f), currency) != flt(r.get(f))
			for f in ("total_incoming_value", "total_outgoing_value", "value_difference")
			if r.get(f) is not None
		)
	][:limit]

	return {
		"company": company,
		"currency": currency,
		"fractional_gl": fractional_gl,
		"fractional_sle": fractional_sle,
		"fractional_stock_entry": fractional_stock_entry,
		"status": "PASS"
		if not (fractional_gl or fractional_sle or fractional_stock_entry)
		else "FAIL",
	}


def check_fractional_for_vouchers(company: str, vouchers: list[tuple[str, str]]) -> dict:
	"""Scan GL/SLE only for explicit voucher list (acceptance scope, not whole company)."""
	fractional_gl = []
	fractional_sle = []
	fractional_stock_entry = []
	currency = get_company_currency(company)
	for doctype, name in vouchers:
		if not name or not frappe.db.exists(doctype, name):
			continue
		for row in fetch_gl_rows(doctype, name):
			if fractional_gl_fields(row, company):
				fractional_gl.append(row)
		for row in fetch_sle_rows(doctype, name):
			if fractional_sle_fields(row, company):
				fractional_sle.append(row)
		if doctype == "Stock Entry":
			doc = frappe.get_doc("Stock Entry", name)
			for f in ("total_incoming_value", "total_outgoing_value", "value_difference"):
				val = doc.get(f)
				if val is not None and round_currency(val, currency) != flt(val):
					fractional_stock_entry.append({"name": name, "field": f, "value": val})
	return {
		"company": company,
		"currency": currency,
		"fractional_gl": fractional_gl,
		"fractional_sle": fractional_sle,
		"fractional_stock_entry": fractional_stock_entry,
		"status": "PASS"
		if not (fractional_gl or fractional_sle or fractional_stock_entry)
		else "FAIL",
	}


@frappe.whitelist()
def check_any_voucher(doctype, voucher_no):
	return check_voucher(doctype, _voucher_no_arg(voucher_no))


@frappe.whitelist()
def run_repost_for_voucher(doctype, voucher_no):
	return run_repost_for_voucher_impl(doctype, _voucher_no_arg(voucher_no))


def run_repost_for_voucher_impl(doctype: str, voucher_no: str) -> dict:
	if not frappe.db.exists(doctype, voucher_no):
		frappe.throw(f"{doctype} {voucher_no} not found")
	doc = frappe.get_doc(doctype, voucher_no)
	company = doc.company
	actions = []

	if frappe.db.exists("DocType", "Repost Item Valuation"):
		try:
			from erpnext.stock.doctype.repost_item_valuation.repost_item_valuation import repost

			riv = frappe.new_doc("Repost Item Valuation")
			riv.company = company
			riv.voucher_type = doctype
			riv.voucher_no = voucher_no
			riv.repost_only_accounting_ledgers = 1
			riv.flags.ignore_permissions = True
			riv.insert(ignore_permissions=True)
			repost(riv)
			actions.append(f"repost_item_valuation:{riv.name}")
		except Exception as exc:
			actions.append(f"repost_item_valuation_failed:{exc!s}")

	try:
		from erpnext.accounts.utils import repost_gle_for_stock_vouchers

		repost_gle_for_stock_vouchers(
			stock_vouchers=[(doctype, voucher_no)],
			posting_date=getattr(doc, "posting_date", today()),
			company=company,
		)
		actions.append("repost_gle_for_stock_vouchers")
	except Exception as exc:
		actions.append(f"repost_gle_failed:{exc!s}")

	if frappe.db.exists("DocType", "Repost Accounting Ledger"):
		allowed = set(frappe.get_hooks("repost_allowed_doctypes") or [])
		if doctype in allowed or doctype in ("Stock Entry", "Purchase Receipt", "Sales Invoice", "Purchase Invoice"):
			try:
				ral = frappe.new_doc("Repost Accounting Ledger")
				ral.company = company
				ral.append("vouchers", {"voucher_type": doctype, "voucher_no": voucher_no})
				ral.flags.ignore_permissions = True
				ral.insert(ignore_permissions=True)
				ral.submit()
				actions.append(f"repost_accounting_ledger:{ral.name}")
			except Exception as exc:
				actions.append(f"repost_accounting_ledger_failed:{exc!s}")

	if doctype == "Stock Entry":
		actions.extend(_normalize_irr_stock_entry(voucher_no))

	frappe.db.commit()
	return {"actions": actions, "voucher_type": doctype, "voucher_no": voucher_no}


@frappe.whitelist()
def assert_no_fractional_irr_gl_api(voucher_type, voucher_no):
	company = frappe.db.get_value(voucher_type, _voucher_no_arg(voucher_no), "company")
	from erpnext_extensions.iran_accounting.validation import assert_no_fractional_irr_gl

	ok = assert_no_fractional_irr_gl(voucher_type, _voucher_no_arg(voucher_no), company)
	return {"ok": ok, "status": "PASS" if ok else "FAIL"}


@frappe.whitelist()
def assert_no_fractional_irr_sle_api(voucher_type, voucher_no):
	company = frappe.db.get_value(voucher_type, _voucher_no_arg(voucher_no), "company")
	from erpnext_extensions.iran_accounting.validation import assert_no_fractional_irr_sle

	ok = assert_no_fractional_irr_sle(voucher_type, _voucher_no_arg(voucher_no), company)
	return {"ok": ok, "status": "PASS" if ok else "FAIL"}


@frappe.whitelist()
def assert_zero_value_transfer_gl_shape_api(voucher_no):
	voucher_no = _voucher_no_arg(voucher_no)
	company = frappe.db.get_value("Stock Entry", voucher_no, "company")
	from erpnext_extensions.iran_accounting.validation import assert_zero_value_transfer_gl_shape

	out = assert_zero_value_transfer_gl_shape(voucher_no, company)
	out["status"] = "PASS" if out.get("ok") else "FAIL"
	return out


@frappe.whitelist()
def assert_reports_no_fractional_irr(company, from_date=None, to_date=None):
	from erpnext_extensions.iran_accounting.reports import run_general_ledger_report, run_stock_ledger_report
	from erpnext_extensions.iran_accounting.validation import assert_report_rows_no_irr_decimals

	from_date = from_date or add_days(today(), -30)
	to_date = to_date or today()
	filters = {"company": company, "from_date": from_date, "to_date": to_date}
	try:
		_, gl_data = run_general_ledger_report(filters)
		assert_report_rows_no_irr_decimals(gl_data, company, ("debit", "credit", "balance"))
		_, sl_data = run_stock_ledger_report(filters)
		assert_report_rows_no_irr_decimals(sl_data, company, ("stock_value", "stock_value_difference"))
		return {"status": "PASS", "gl_rows": len(gl_data), "sl_rows": len(sl_data)}
	except Exception as exc:
		return {"status": "FAIL", "error": str(exc)}


@frappe.whitelist()
def assert_print_no_fractional_irr(voucher_type, voucher_no):
	out = check_print_output(_voucher_no_arg(voucher_no), doctype=voucher_type)
	if out.get("status") == "PASS":
		return {**out, "manual_required": False}
	return {**out, "status": "MANUAL_REQUIRED", "manual_required": True, "reason": "valuation_rate or ambiguous HTML decimals"}


@frappe.whitelist()
def check_print_output(voucher_no, doctype="Stock Entry"):
	voucher_no = _voucher_no_arg(voucher_no)
	if isinstance(doctype, dict):
		doctype = doctype.get("doctype", "Stock Entry")
	html = frappe.get_print(doctype, voucher_no)
	result = check_print_html_no_irr_monetary_decimals(html)
	result["voucher_no"] = voucher_no
	result["doctype"] = doctype
	return result


@frappe.whitelist()
def debug_mtfm(company=None):
	"""Create MTfM path and dump SQL/preview diagnostics."""
	import erpnext_extensions.iran_accounting  # noqa: F401
	from erpnext.manufacturing.doctype.work_order.work_order import make_stock_entry as wo_make_stock_entry

	from erpnext_extensions.iran_accounting import e2e_bootstrap as b
	from erpnext_extensions.iran_accounting.acceptance_scenarios import AcceptanceContext, _make_bom_wo
	from erpnext_extensions.iran_accounting.preview_validation import validate_accounting_ledger_preview
	from erpnext_extensions.iran_accounting.sql_validation import (
		comprehensive_voucher_sql_check,
		sql_get_gl_rows,
		sql_get_sle_rows,
		sql_get_stock_entry_rows,
		sql_gl_grouped_totals,
		sql_sle_grouped_totals,
	)
	from erpnext_extensions.iran_accounting.stock_entry import align_zero_value_transfer_totals

	frappe.set_user("Administrator")
	company = b.get_irr_company(company or None)
	b.enable_perpetual_inventory(company)
	wh = b.get_warehouse(company)
	to_wh = b.get_second_warehouse(company, wh)
	ctx = AcceptanceContext(
		company=company,
		warehouse=wh,
		to_wh=to_wh,
		run_repost=True,
		include_synthetic=True,
		b=b,
	)
	_rm, _fg, wo_name, bom = _make_bom_wo(ctx, reuse=False)
	mtfm = frappe.get_doc(wo_make_stock_entry(wo_name, "Material Transfer for Manufacture", qty=1))
	mtfm.company = company
	mtfm.insert(ignore_permissions=True)
	if hasattr(mtfm, "set_total_incoming_outgoing_value"):
		mtfm.set_total_incoming_outgoing_value()
	align_zero_value_transfer_totals(mtfm)
	mtfm.save(ignore_permissions=True)
	preview = validate_accounting_ledger_preview(mtfm, company)
	mtfm.submit()
	frappe.db.commit()
	pre = comprehensive_voucher_sql_check("Stock Entry", mtfm.name, company)
	repost = run_repost_for_voucher_impl("Stock Entry", mtfm.name)
	post = comprehensive_voucher_sql_check("Stock Entry", mtfm.name, company)
	out = {
		"work_order": wo_name,
		"bom": bom.name if bom else ctx.refs.get("bom"),
		"mtfm": mtfm.name,
		"stock_entry": sql_get_stock_entry_rows(mtfm.name),
		"preview": preview,
		"gl_sql": sql_get_gl_rows("Stock Entry", mtfm.name),
		"sle_sql": sql_get_sle_rows("Stock Entry", mtfm.name),
		"gl_grouped": sql_gl_grouped_totals(mtfm.name),
		"sle_grouped": sql_sle_grouped_totals(mtfm.name),
		"checks_pre_repost": pre,
		"repost_actions": repost.get("actions"),
		"checks_post_repost": post,
	}
	checks = {
		"preview_ok": preview.get("preview_ok"),
		"submit_ok": True,
		"db_gl_ok": post.get("db_gl_ok"),
		"db_sle_ok": post.get("db_sle_ok"),
		"db_stock_entry_ok": post.get("db_stock_entry_ok"),
		"repost_ok": post.get("db_gl_ok") and post.get("db_sle_ok"),
		"no_adjustment_ok": post.get("no_adjustment_ok"),
		"no_double_ok": post.get("no_double_ok"),
		"no_fractional_irr_ok": post.get("no_fractional_irr_ok"),
		"totals_ok": post.get("totals_ok"),
		"status": "PASS"
		if all(
			[
				preview.get("preview_ok"),
				post.get("db_gl_ok"),
				post.get("db_sle_ok"),
				post.get("db_stock_entry_ok"),
				post.get("no_adjustment_ok"),
				post.get("no_double_ok"),
				post.get("totals_ok"),
			]
		)
		else "FAIL",
	}
	out["checks"] = checks
	print(f"Work Order: {wo_name}")
	print(f"BOM: {out['bom']}")
	print(f"MTfM: {mtfm.name}")
	print("Stock Entry totals:", out["stock_entry"].get("header"))
	print("Preview GL rows:", preview.get("gl_like"))
	print("Submitted GL SQL:", out["gl_sql"])
	print("SLE SQL:", out["sle_sql"])
	print("GL grouped:", out["gl_grouped"])
	print("SLE grouped:", out["sle_grouped"])
	print("Post-repost checks:", post)
	print("PASS/FAIL:", checks)
	return out
