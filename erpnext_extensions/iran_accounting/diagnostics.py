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
	GL_AMOUNT_FIELDS,
	amount_is_fractional,
	check_print_html_no_irr_monetary_decimals,
	fetch_gl_rows,
	fetch_sle_rows,
	fractional_gl_fields,
	fractional_sle_fields,
	gl_debit_credit_totals,
	is_doubled_gl,
	is_irr_currency,
	stock_adj_round_off_rows,
	summarize_voucher_check,
)


def _normalize_irr_voucher_ledgers(voucher_type: str, voucher_no: str) -> list[str]:
	company = frappe.db.get_value(voucher_type, voucher_no, "company")
	if not company or not is_irr_company(company):
		return []

	actions: list[str] = []
	if voucher_type == "Stock Entry":
		se = frappe.get_doc("Stock Entry", voucher_no)
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
		filters={"voucher_type": voucher_type, "voucher_no": voucher_no, "is_cancelled": 0},
	):
		sle = frappe.get_doc("Stock Ledger Entry", sle_name)
		round_sle_monetary_fields(sle, company)
		sle.db_update()
	actions.append("normalized_sle_monetary_fields")

	for gle_name in frappe.get_all(
		"GL Entry",
		pluck="name",
		filters={"voucher_type": voucher_type, "voucher_no": voucher_no, "is_cancelled": 0},
	):
		gle = frappe.get_doc("GL Entry", gle_name)
		round_gl_entry_amounts(gle)
		gle.db_update()
	actions.append("normalized_gl_entry_amounts")

	if voucher_type == "Stock Entry":
		_sync_bins_from_voucher_sles(voucher_no, company)
		actions.append("synced_bins_from_voucher_sles")
	return actions


def _normalize_irr_stock_entry(voucher_no: str) -> list[str]:
	return _normalize_irr_voucher_ledgers("Stock Entry", voucher_no)


def _sync_bins_from_voucher_sles(voucher_no: str, company: str) -> None:
	rows = frappe.get_all(
		"Stock Ledger Entry",
		filters={"voucher_type": "Stock Entry", "voucher_no": voucher_no, "is_cancelled": 0, "company": company},
		fields=["name", "item_code", "warehouse", "qty_after_transaction", "stock_value", "valuation_rate", "creation"],
		order_by="item_code, warehouse, creation",
	)
	last: dict[tuple[str, str], dict] = {}
	for row in rows:
		last[(row.item_code, row.warehouse)] = row
	for (item_code, warehouse), sle in last.items():
		full = frappe.get_doc("Stock Ledger Entry", sle.name)
		if _has_later_sle(
			company, item_code, warehouse, full.posting_date, full.posting_time, full.creation
		):
			continue
		bin_name = frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": warehouse}, "name")
		if not bin_name:
			continue
		frappe.db.set_value(
			"Bin",
			bin_name,
			{
				"actual_qty": sle.qty_after_transaction,
				"stock_value": sle.stock_value,
				"valuation_rate": sle.valuation_rate,
			},
			update_modified=False,
		)


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
def check_company_fractional_irr(company=None, limit=100, legacy_before=None):
	"""Company-wide fractional scan with release buckets."""
	return classify_company_fractional_irr(company=company, limit=limit, legacy_before=legacy_before)


def classify_company_fractional_irr(
	company=None,
	limit: int = 500,
	legacy_before: str | None = None,
) -> dict:
	"""Classify fractional monetary rows for IRR companies (full-company scan)."""
	from erpnext_extensions.iran_accounting.validation import (
		GL_ROW_FIELDS,
		currency_for_gl_field,
		fractional_gl_fields,
		fractional_sle_fields,
	)

	limit = int(limit or 500)
	legacy_before = legacy_before or "2026-06-20"
	company = company or frappe.db.get_value("Company", {"default_currency": "IRR"}, "name")
	if not company or not is_irr_company(company):
		return {
			"company": company,
			"FAIL_NEW_IRR_FRACTIONAL": [],
			"LEGACY_REPOST_REQUIRED": [],
			"ALLOWED_FC_DECIMAL": [],
			"fail_new_irr_fractional": [],
			"legacy_repost_required": [],
			"allowed_fc_decimal": [],
			"status": "SKIP",
		}

	company_currency = get_company_currency(company)
	fail_new: list[dict] = []
	legacy: list[dict] = []
	allowed_fc: list[dict] = []
	fail_new_vouchers: set[tuple[str, str]] = set()
	fc_account_fields = ("debit_in_account_currency", "credit_in_account_currency")

	gl_fields_sql = ", ".join(f"`{f}`" for f in GL_ROW_FIELDS if f != "name") + ", name, posting_date, voucher_type, voucher_no"
	gl_rows = frappe.db.sql(
		f"""
		select {gl_fields_sql}
		from `tabGL Entry`
		where company = %s and is_cancelled = 0
		order by posting_date desc, creation desc
		""",
		(company,),
		as_dict=True,
	)

	for row in gl_rows:
		acct_cur = (row.get("account_currency") or company_currency).upper()
		for field in GL_AMOUNT_FIELDS:
			val = row.get(field)
			if val in (None, ""):
				continue
			cur = currency_for_gl_field(row, field, company_currency)
			if not amount_is_fractional(val, cur):
				continue
			entry = {
				"doctype": "GL Entry",
				"name": row.get("name"),
				"voucher_type": row.get("voucher_type"),
				"voucher_no": row.get("voucher_no"),
				"posting_date": str(row.get("posting_date") or ""),
				"field": field,
				"value": val,
				"currency": cur,
				"account_currency": acct_cur,
			}
			if field in fc_account_fields and acct_cur in ("USD", "EUR"):
				allowed_fc.append(entry)
				continue
			if not is_irr_currency(cur):
				continue
			if entry["posting_date"] and entry["posting_date"] < legacy_before:
				legacy.append(entry)
			else:
				fail_new.append(entry)
				vt, vn = entry.get("voucher_type"), entry.get("voucher_no")
				if vt and vn:
					fail_new_vouchers.add((vt, vn))

	sle_rows = frappe.db.sql(
		"""
		select name, voucher_no, voucher_type, posting_date, stock_value, stock_value_difference,
			valuation_rate, incoming_rate, actual_qty, qty_after_transaction, company
		from `tabStock Ledger Entry`
		where company = %s and is_cancelled = 0
		order by posting_date desc, creation desc
		""",
		(company,),
		as_dict=True,
	)
	for row in sle_rows:
		for viol in fractional_sle_fields(row, company):
			entry = {
				"doctype": "Stock Ledger Entry",
				**viol,
				"voucher_no": row.get("voucher_no"),
				"voucher_type": row.get("voucher_type"),
				"posting_date": str(row.get("posting_date") or ""),
			}
			pd = entry["posting_date"]
			if pd and pd < legacy_before:
				legacy.append(entry)
			else:
				fail_new.append(entry)
				vt, vn = entry.get("voucher_type"), entry.get("voucher_no")
				if vt and vn:
					fail_new_vouchers.add((vt, vn))

	ste_rows = frappe.db.sql(
		"""
		select name, posting_date, total_incoming_value, total_outgoing_value, value_difference
		from `tabStock Entry`
		where company = %s and docstatus = 1
		order by posting_date desc, creation desc
		""",
		(company,),
		as_dict=True,
	)
	for row in ste_rows:
		for f in ("total_incoming_value", "total_outgoing_value", "value_difference"):
			val = row.get(f)
			if val is None or not amount_is_fractional(val, company_currency):
				continue
			entry = {
				"doctype": "Stock Entry",
				"name": row.get("name"),
				"field": f,
				"value": val,
				"posting_date": str(row.get("posting_date") or ""),
			}
			pd = entry["posting_date"]
			if pd and pd < legacy_before:
				legacy.append(entry)
			else:
				fail_new.append(entry)
				fail_new_vouchers.add(("Stock Entry", row.get("name")))

	# de-dupe samples for output
	def _cap(items, n=limit):
		return items[:n]

	result = {
		"company": company,
		"currency": company_currency,
		"legacy_before": legacy_before,
		"FAIL_NEW_IRR_FRACTIONAL": _cap(fail_new),
		"LEGACY_REPOST_REQUIRED": _cap(legacy),
		"ALLOWED_FC_DECIMAL": _cap(allowed_fc),
		"fail_new_irr_fractional": _cap(fail_new),
		"legacy_repost_required": _cap(legacy),
		"allowed_fc_decimal": _cap(allowed_fc),
		"counts": {
			"fail_new_irr_fractional": len(fail_new),
			"legacy_repost_required": len(legacy),
			"allowed_fc_decimal": len(allowed_fc),
			"fail_new_vouchers": len(fail_new_vouchers),
		},
		"fail_new_voucher_keys": sorted(fail_new_vouchers),
		"status": "PASS" if not fail_new else "FAIL",
		# backward compat
		"fractional_gl": fail_new + legacy,
		"fractional_sle": [],
		"fractional_stock_entry": [],
	}
	print(
		f"Company fractional scan {company}: "
		f"FAIL_NEW={len(fail_new)} LEGACY={len(legacy)} ALLOWED_FC={len(allowed_fc)}"
	)
	return result


@frappe.whitelist()
def repair_company_fractional_irr(company=None, legacy_before=None, max_passes: int = 4):
	"""Normalize IRR integer violations on post-cutoff vouchers (acceptance cleanup / release repair)."""
	company = company or frappe.db.get_value("Company", {"default_currency": "IRR"}, "name")
	legacy_before = legacy_before or "2026-06-20"
	repair_log: list[dict] = []
	for _pass in range(int(max_passes or 4)):
		scan = classify_company_fractional_irr(
			company=company, legacy_before=legacy_before, limit=25
		)
		if not (scan.get("counts") or {}).get("fail_new_irr_fractional"):
			scan["repair_log"] = repair_log
			return scan
		for voucher_type, voucher_no in scan.get("fail_new_voucher_keys") or []:
			if not voucher_type or not voucher_no:
				continue
			if not frappe.db.exists(voucher_type, voucher_no):
				continue
			actions = _normalize_irr_voucher_ledgers(voucher_type, voucher_no)
			if voucher_type == "Stock Entry":
				try:
					repost_and_check_stock_entry(voucher_no)
					actions.append("repost_and_check_stock_entry")
				except Exception as exc:
					actions.append(f"repost_failed:{exc!s}")
			repair_log.append(
				{"voucher_type": voucher_type, "voucher_no": voucher_no, "actions": actions}
			)
		frappe.db.commit()
	scan = classify_company_fractional_irr(company=company, legacy_before=legacy_before, limit=25)
	scan["repair_log"] = repair_log
	return scan


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


def check_irr_fractional_rows(company=None, limit=100):
	return classify_company_fractional_irr(company=company, limit=limit)


def check_fractional_for_vouchers(company: str, vouchers: list[tuple[str, str]]) -> dict:
	"""Scan GL/SLE only for explicit voucher list (acceptance scope, not whole company)."""
	fail_new_irr_fractional: list[dict] = []
	allowed_fc_decimal: list[dict] = []
	fractional_sle: list = []
	fractional_stock_entry: list = []
	currency = get_company_currency(company)
	for doctype, name in vouchers:
		if not name or not frappe.db.exists(doctype, name):
			continue
		for row in fetch_gl_rows(doctype, name):
			for viol in fractional_gl_fields(row, company):
				fail_new_irr_fractional.append(
					{**viol, "voucher": name, "doctype": doctype, "gle": row.get("name")}
				)
		for row in fetch_sle_rows(doctype, name):
			if fractional_sle_fields(row, company):
				fractional_sle.append({**row, "voucher": name, "doctype": doctype})
		if doctype == "Stock Entry":
			doc = frappe.get_doc("Stock Entry", name)
			for f in ("total_incoming_value", "total_outgoing_value", "value_difference"):
				val = doc.get(f)
				if val is not None and round_currency(val, currency) != flt(val):
					fractional_stock_entry.append({"name": name, "field": f, "value": val})
	blocking = bool(fail_new_irr_fractional or fractional_sle or fractional_stock_entry)
	return {
		"company": company,
		"currency": currency,
		"fail_new_irr_fractional": fail_new_irr_fractional,
		"allowed_fc_decimal": allowed_fc_decimal,
		"legacy_repost_required": [],
		"fractional_gl": fail_new_irr_fractional,
		"fractional_sle": fractional_sle,
		"fractional_stock_entry": fractional_stock_entry,
		"status": "PASS" if not blocking else "FAIL",
	}


@frappe.whitelist()
def check_any_voucher(doctype, voucher_no):
	return check_voucher(doctype, _voucher_no_arg(voucher_no))


@frappe.whitelist()
def run_repost_for_voucher(doctype, voucher_no):
	return run_repost_for_voucher_impl(doctype, _voucher_no_arg(voucher_no))


def run_repost_for_voucher_impl(doctype: str, voucher_no: str, normalize_after: bool = True) -> dict:
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

	if doctype == "Stock Entry" and normalize_after:
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
		columns, sl_data = run_stock_ledger_report(filters)
		from erpnext_extensions.iran_accounting.reports import stock_ledger_report_monetary_fields

		sl_fields = tuple(stock_ledger_report_monetary_fields(columns, filters))
		assert_report_rows_no_irr_decimals(sl_data, company, sl_fields)
		return {"status": "PASS", "gl_rows": len(gl_data), "sl_rows": len(sl_data), "sl_fields": sl_fields}
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


@frappe.whitelist()
def check_stock_ledger_report(
	company=None,
	voucher_no=None,
	from_date=None,
	to_date=None,
	voucher_type="Stock Entry",
):
	"""Diagnostics for Stock Ledger report / export / DB (IRR monetary decimals)."""
	import erpnext_extensions.iran_accounting  # noqa: F401
	from erpnext_extensions.iran_accounting.monkey_patches import apply_monkey_patches
	from erpnext_extensions.iran_accounting.reports import (
		run_stock_ledger_report,
		stock_ledger_report_monetary_fields,
	)
	from erpnext_extensions.iran_accounting.stock_ledger_report import (
		default_stock_ledger_filters,
		export_stock_ledger_xlsx_rows,
		fractional_cells_in_report_rows,
		fractional_monetary_in_xlsx,
		monetary_fieldnames_from_columns,
		quantity_fieldnames_from_columns,
		sle_db_fractional_values,
		sle_db_snapshot,
	)

	apply_monkey_patches()
	frappe.set_user("Administrator")
	company = company or frappe.db.get_value("Company", {"default_currency": "IRR"}, "name")
	filters = default_stock_ledger_filters(company, voucher_no=voucher_no, from_date=from_date, to_date=to_date)
	columns, data = run_stock_ledger_report(filters)
	monetary_fields = tuple(stock_ledger_report_monetary_fields(columns, filters))
	qty_fields = tuple(quantity_fieldnames_from_columns(columns))

	report_fractional = fractional_cells_in_report_rows(data, company, monetary_fields)
	sle_rows = sle_db_snapshot(voucher_type, voucher_no) if voucher_no else []
	db_frac = sle_db_fractional_values(company, sle_rows)
	db_ok = not db_frac.get("value_fields") and not db_frac.get("rate_fields")

	export_columns, xlsx_rows = export_stock_ledger_xlsx_rows(filters)
	export_fractional = fractional_monetary_in_xlsx(export_columns, xlsx_rows, company)
	export_ok = not export_fractional

	report_ok = not report_fractional
	status = "PASS" if db_ok and report_ok and export_ok else "FAIL"

	out = {
		"status": status,
		"company": company,
		"voucher_no": voucher_no,
		"filters": filters,
		"db_ok": db_ok,
		"report_ok": report_ok,
		"export_ok": export_ok,
		"monetary_fields": monetary_fields,
		"quantity_fields": qty_fields,
		"sle_db_rows": sle_rows,
		"db_fractional_value_fields": db_frac.get("value_fields"),
		"db_fractional_rate_fields": db_frac.get("rate_fields"),
		"report_fractional_monetary": report_fractional,
		"export_fractional_monetary": export_fractional,
		"report_rows": data,
		"report_row_count": len(data or []),
	}
	print(f"Stock Ledger diagnostics company={company} voucher={voucher_no}")
	print(f"status={status} db_ok={db_ok} report_ok={report_ok} export_ok={export_ok}")
	if db_frac.get("value_fields"):
		print("DB fractional VALUE fields:", db_frac["value_fields"])
	if db_frac.get("rate_fields"):
		print("DB fractional RATE fields (informational):", db_frac["rate_fields"])
	if report_fractional:
		print("Report fractional monetary:", report_fractional[:20])
	if export_fractional:
		print("Export fractional monetary:", export_fractional[:20])
	return out


def _previous_sle_for_row(sle: dict) -> dict | None:
	"""SLE immediately before this row (same item, warehouse, company)."""
	posting_datetime = f"{sle.get('posting_date') if isinstance(sle, dict) else sle.posting_date} {sle.get('posting_time') if isinstance(sle, dict) else sle.posting_time}"
	rows = frappe.db.sql(
		"""
		select name, stock_value, qty_after_transaction, valuation_rate, stock_value_difference
		from `tabStock Ledger Entry`
		where company = %(company)s
		  and item_code = %(item_code)s
		  and warehouse = %(warehouse)s
		  and is_cancelled = 0
		  and (
			posting_datetime < %(posting_datetime)s
			or (posting_datetime = %(posting_datetime)s and creation < %(creation)s)
		  )
		order by posting_datetime desc, creation desc
		limit 1
		""",
		{
			"company": sle.get("company") if isinstance(sle, dict) else sle.company,
			"item_code": sle.get("item_code") if isinstance(sle, dict) else sle.item_code,
			"warehouse": sle.get("warehouse") if isinstance(sle, dict) else sle.warehouse,
			"posting_datetime": posting_datetime,
			"creation": sle.get("creation") if isinstance(sle, dict) else sle.creation,
		},
		as_dict=True,
	)
	return rows[0] if rows else None


def _gl_residual_for_stock_entry(voucher_no: str, company: str) -> dict:
	gl_rows = fetch_gl_rows("Stock Entry", voucher_no)
	debit, credit = gl_debit_credit_totals(gl_rows)
	adj = stock_adj_round_off_rows(gl_rows, company)
	se = frappe.get_cached_value(
		"Stock Entry",
		voucher_no,
		["total_incoming_value", "total_outgoing_value", "value_difference"],
		as_dict=True,
	)
	currency = get_company_currency(company)
	inc = round_currency(se.total_incoming_value, currency)
	out = round_currency(se.total_outgoing_value, currency)
	return {
		"gl_balanced": flt(debit) == flt(credit),
		"gl_debit": debit,
		"gl_credit": credit,
		"stock_entry_incoming": inc,
		"stock_entry_outgoing": out,
		"gl_matches_incoming": flt(debit) == flt(inc),
		"gl_matches_outgoing": flt(credit) == flt(out),
		"stock_adjustment_or_round_off": adj,
		"residual_posted_to_gl": bool(adj) or abs(flt(debit) - flt(credit)) > 0,
	}


def _has_later_sle(company: str, item_code: str, warehouse: str, posting_date, posting_time, creation) -> bool:
	posting_datetime = f"{posting_date} {posting_time}"
	return bool(
		frappe.db.sql(
			"""
			select 1 from `tabStock Ledger Entry`
			where company = %s and item_code = %s and warehouse = %s and is_cancelled = 0
			  and (
				posting_datetime > %s
				or (posting_datetime = %s and creation > %s)
			  )
			limit 1
			""",
			(company, item_code, warehouse, posting_datetime, posting_datetime, creation),
		)
	)


@frappe.whitelist()
def check_stock_value_residual(voucher_no: str, company: str | None = None) -> dict:
	"""Validate SLE stock_value / movement residuals for an IRR stock voucher (release blocker diagnostics)."""
	voucher_no = _voucher_no_arg(voucher_no)
	if not frappe.db.exists("Stock Entry", voucher_no):
		frappe.throw(f"Stock Entry {voucher_no} not found")

	se = frappe.get_doc("Stock Entry", voucher_no)
	company = company or se.company
	if not is_irr_company(company):
		return {"status": "SKIP", "reason": "not IRR company", "voucher_no": voucher_no}

	currency = get_company_currency(company)
	gl_info = _gl_residual_for_stock_entry(voucher_no, company)
	sle_docs = frappe.get_all(
		"Stock Ledger Entry",
		filters={"voucher_type": "Stock Entry", "voucher_no": voucher_no, "is_cancelled": 0},
		fields=[
			"name",
			"item_code",
			"warehouse",
			"actual_qty",
			"qty_after_transaction",
			"incoming_rate",
			"valuation_rate",
			"stock_value",
			"stock_value_difference",
			"posting_date",
			"posting_time",
			"creation",
			"company",
		],
		order_by="item_code, warehouse, creation",
	)

	from collections import defaultdict

	last_sle_by_wh: dict[tuple[str, str], str] = {}
	grouped: dict[tuple[str, str], list] = defaultdict(list)
	for sle in sle_docs:
		key = (sle.item_code, sle.warehouse)
		grouped[key].append(sle)
		last_sle_by_wh[key] = sle.name

	lines = []
	any_fail = False
	for sle in sle_docs:
		prev = _previous_sle_for_row(sle)
		value_before = flt(prev.stock_value) if prev else 0.0
		qty_before = flt(prev.qty_after_transaction) if prev else 0.0
		movement_qty = flt(sle.actual_qty)
		movement_value = flt(sle.stock_value_difference)
		qty_after = flt(sle.qty_after_transaction)
		value_after = flt(sle.stock_value)
		expected_after = round_currency(value_before + movement_value, currency)
		identity_residual = flt(value_after - expected_after, 0)
		rate = flt(sle.valuation_rate)
		rate_product = round_currency(qty_after * rate, currency) if qty_after else 0
		rate_product_residual = abs(flt(value_after - rate_product))
		movement_vs_balance = abs(value_after) - abs(movement_value)
		max_rate_residual = max(1, int(abs(qty_after)) + 1) if qty_after else 0

		bin_row = frappe.db.get_value(
			"Bin",
			{"item_code": sle.item_code, "warehouse": sle.warehouse},
			["actual_qty", "valuation_rate", "stock_value"],
			as_dict=True,
		)
		is_last_for_wh = sle.name == last_sle_by_wh.get((sle.item_code, sle.warehouse))
		bin_matches_sle = True
		bin_skipped_later_activity = False
		if is_last_for_wh:
			if _has_later_sle(
				company, sle.item_code, sle.warehouse, sle.posting_date, sle.posting_time, sle.creation
			):
				bin_skipped_later_activity = True
			else:
				bin_matches_sle = bool(
					bin_row
					and flt(bin_row.actual_qty) == qty_after
					and flt(bin_row.stock_value) == value_after
				)
		orphan_value = qty_after == 0 and value_after != 0

		line_ok = (
			identity_residual == 0
			and not orphan_value
			and bin_matches_sle
			and rate_product_residual <= max_rate_residual
		)
		if not line_ok:
			any_fail = True

		lines.append(
			{
				"sle": sle.name,
				"item_code": sle.item_code,
				"warehouse": sle.warehouse,
				"qty_before": qty_before,
				"value_before": value_before,
				"movement_qty": movement_qty,
				"movement_value": movement_value,
				"qty_after": qty_after,
				"value_after": value_after,
				"expected_value_after": expected_after,
				"identity_residual": identity_residual,
				"movement_vs_balance": movement_vs_balance,
				"valuation_rate": rate,
				"qty_after_times_rate": rate_product,
				"rate_product_residual": rate_product_residual,
				"max_allowed_rate_residual": max_rate_residual,
				"residual_posted_to_gl": gl_info["residual_posted_to_gl"],
				"bin_matches_sle": bin_matches_sle,
				"bin_skipped_later_activity": bin_skipped_later_activity,
				"is_last_sle_for_item_warehouse": is_last_for_wh,
				"bin": bin_row if is_last_for_wh else None,
				"status": "PASS" if line_ok else "FAIL",
				"notes": (
					"movement_vs_balance is not movement amount when qty_after>0; "
					"check identity_residual and rate_product_residual instead."
					if qty_after and movement_vs_balance
					else ""
				),
			}
		)

	overall = "PASS" if lines and not any_fail else "FAIL"
	voucher_gl_ok = (
		gl_info["gl_balanced"]
		and gl_info["gl_matches_incoming"]
		and gl_info["gl_matches_outgoing"]
	)
	if overall == "PASS" and not voucher_gl_ok:
		overall = "FAIL"
	return {
		"status": overall,
		"voucher_no": voucher_no,
		"company": company,
		"purpose": se.purpose,
		"gl": gl_info,
		"voucher_gl_ok": voucher_gl_ok,
		"lines": lines,
	}
