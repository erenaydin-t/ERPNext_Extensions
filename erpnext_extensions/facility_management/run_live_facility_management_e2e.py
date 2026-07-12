"""Live E2E: Facility Management (development.localhost) Tests 1–12.

bench --site development.localhost execute \\
  erpnext_extensions.facility_management.run_live_facility_management_e2e.run
"""

from __future__ import annotations

import json
import time

import frappe
from frappe.utils import cint, flt, getdate, today

from erpnext_extensions.facility_management.doctype.facility.facility import (
	close_facility,
	create_receipt_journal_entry,
)
from erpnext_extensions.facility_management.facility_accounting import (
	_validate_receipt_je_dimensions,
	_validate_repayment_je_dimensions,
	get_facility_dimension_fieldname,
)
from erpnext_extensions.facility_management.facility_accounting_dimensions import (
	provision_facility_accounting_dimension,
)
from erpnext_extensions.facility_management.facility_balances import get_facility_balance_row
from erpnext_extensions.facility_management.report.facility_balance.facility_balance import (
	execute as balance_execute,
)
from erpnext_extensions.facility_management.report.facility_ledger.facility_ledger import (
	execute as ledger_execute,
)


def _log(title: str, payload):
	print(f"\n=== {title} ===")
	print(json.dumps(payload, indent=2, default=str))


from erpnext_extensions.facility_management.facility_e2e_context import site_e2e_context


def _new_facility(ctx, *, suffix: str, principal, profit, opening=False, **extra):
	doc = frappe.new_doc("Facility")
	doc.facility_name = f"E2E Facility {suffix}"
	doc.company = ctx["company"]
	doc.bank = ctx["bank"]
	doc.contract_date = getdate(today())
	doc.principal_amount = principal
	doc.profit_amount = profit
	doc.loan_payable_account = ctx["loan_payable"]
	doc.bank_account = ctx["bank_gl"]
	doc.deferred_loan_interest_account = ctx["deferred"]
	doc.interest_expense_account = ctx.get("interest")
	doc.penalty_expense_account = ctx["penalty"]
	doc.is_opening_facility = 1 if opening else 0
	doc.status = extra.pop("status", "Draft")
	for k, v in extra.items():
		doc.set(k, v)
	doc.insert(ignore_permissions=True)
	frappe.db.commit()
	return doc


def _je_rows(je_name: str | None, dim_fn: str | None) -> list[dict]:
	if not je_name:
		return []
	je = frappe.get_doc("Journal Entry", je_name)
	out = []
	for row in je.accounts:
		item = {
			"account": row.account,
			"debit": flt(row.debit_in_account_currency),
			"credit": flt(row.credit_in_account_currency),
		}
		if dim_fn:
			item[dim_fn] = getattr(row, dim_fn, None)
		out.append(item)
	return out


def _gl_rows(je_name: str | None, dim_fn: str | None) -> list[dict]:
	if not je_name or not dim_fn:
		return []
	fields = ["account", "debit", "credit", dim_fn]
	return frappe.get_all(
		"GL Entry",
		filters={"voucher_type": "Journal Entry", "voucher_no": je_name, "is_cancelled": 0},
		fields=fields,
		order_by="idx asc",
	)


def _assert_dim(rows: list[dict], dim_fn: str, facility_name: str, label: str, errors: list[str]):
	for r in rows:
		if r.get(dim_fn) != facility_name:
			errors.append(
				f"{label}: account {r.get('account')} dim={r.get(dim_fn)!r} expected {facility_name!r}"
			)


def _assert_receipt_excel_dimensions(facility_doc, je_name: str, errors: list[str]) -> None:
	try:
		_validate_receipt_je_dimensions(je_name, facility_doc)
	except Exception as e:
		errors.append(f"Receipt JE Excel dimensions: {e}")


def _assert_repayment_excel_dimensions(facility_doc, repayment_doc, je_name: str, errors: list[str]) -> None:
	try:
		_validate_repayment_je_dimensions(je_name, facility_doc, repayment_doc)
	except Exception as e:
		errors.append(f"Repayment JE Excel dimensions: {e}")


def run():
	errors: list[str] = []
	results: dict = {"tests": {}}
	ctx = site_e2e_context()
	provision_facility_accounting_dimension()
	frappe.db.commit()
	dim_fn = get_facility_dimension_fieldname()
	suffix = str(int(time.time()))

	# Test 1 — Module / DocTypes
	t1 = {
		"module_def": frappe.db.exists("Module Def", "Facility Management"),
		"facility_doctype": frappe.db.exists("DocType", "Facility"),
		"repayment_doctype": frappe.db.exists("DocType", "Facility Repayment"),
		"workspace": frappe.db.exists("Workspace", "Facility Management"),
	}
	results["tests"]["1_module_and_doctypes"] = t1
	_log("Test 1 Module / DocTypes", t1)
	if not all(t1.values()):
		errors.append(f"Test 1 failed: {t1}")

	# Test 2 — Accounting Dimension
	t2 = {
		"dimension_fieldname": dim_fn,
		"accounting_dimension": frappe.db.get_value(
			"Accounting Dimension", {"document_type": "Facility"}, "name"
		),
	}
	results["tests"]["2_accounting_dimension"] = t2
	_log("Test 2 Accounting Dimension", t2)
	if not dim_fn:
		errors.append("Test 2: Facility Accounting Dimension field missing on JE")

	# Test 3 — Receipt JE (10B principal, 3B profit)
	principal = 10_000_000_000.0
	profit = 3_000_000_000.0
	fac = _new_facility(ctx, suffix=suffix, principal=principal, profit=profit, receive_date=getdate(today()))
	receipt = create_receipt_journal_entry(fac.name)
	fac.reload()
	t3 = {
		"facility": fac.name,
		"receipt_journal_entry": fac.receipt_journal_entry,
		"status": fac.status,
		"received_amount": flt(fac.received_amount),
	}
	results["tests"]["3_receipt_je"] = t3
	_log("Test 3 Receipt JE", t3)
	if fac.receipt_journal_entry != receipt.get("journal_entry") or fac.status != "Active":
		errors.append(f"Test 3: receipt/status mismatch {t3}")
	if flt(fac.received_amount) != principal:
		errors.append(f"Test 3: received_amount {fac.received_amount} != {principal}")

	# Test 4 — JE + GL Facility dimension
	je_name = fac.receipt_journal_entry
	je_data = _je_rows(je_name, dim_fn)
	gl_data = _gl_rows(je_name, dim_fn)
	t4 = {"journal_entry": je_name, "je_rows": je_data, "gl_rows": gl_data}
	results["tests"]["4_dimension_on_je_gl"] = t4
	_log("Test 4 JE/GL dimension", t4)
	_assert_receipt_excel_dimensions(fac, je_name, errors)
	if len(je_data) != 4:
		errors.append(f"Test 4: expected 4 receipt JE rows, got {len(je_data)}")
	if len([r for r in je_data if r.get("account") == fac.loan_payable_account and r.get("credit")]) != 2:
		errors.append("Test 4: expected two Loan Payable credit rows")

	# Test 5 — Partial repayment
	rep1 = frappe.new_doc("Facility Repayment")
	rep1.facility = fac.name
	rep1.posting_date = getdate(today())
	rep1.principal_amount = 200_000_000.0
	rep1.profit_amount = 50_000_000.0
	rep1.insert(ignore_permissions=True)
	rep1.submit()
	frappe.db.commit()
	fac.reload()
	bal = get_facility_balance_row(fac)
	t5 = {
		"repayment": rep1.name,
		"journal_entry": rep1.journal_entry,
		"balance": bal,
	}
	results["tests"]["5_partial_repayment"] = t5
	_log("Test 5 Partial repayment", t5)
	if flt(bal["paid_principal"]) != 200_000_000.0 or flt(bal["paid_profit"]) != 50_000_000.0:
		errors.append(f"Test 5: balance paid mismatch {bal}")
	_assert_repayment_excel_dimensions(fac, rep1, rep1.journal_entry, errors)

	# Test 6 — Penalty repayment row
	rep2 = frappe.new_doc("Facility Repayment")
	rep2.facility = fac.name
	rep2.posting_date = getdate(today())
	rep2.penalty_amount = 1_000_000.0
	rep2.insert(ignore_permissions=True)
	rep2.submit()
	frappe.db.commit()
	pen_rows = _je_rows(rep2.journal_entry, dim_fn)
	t6 = {"repayment": rep2.name, "journal_entry": rep2.journal_entry, "je_rows": pen_rows}
	results["tests"]["6_penalty_repayment"] = t6
	_log("Test 6 Penalty repayment", t6)
	pen_debit = [r for r in pen_rows if flt(r["debit"]) == 1_000_000.0]
	if not pen_debit:
		errors.append("Test 6: penalty debit row missing")
	_assert_repayment_excel_dimensions(fac, rep2, rep2.journal_entry, errors)

	# Test 7 — Close blocked
	close_blocked = None
	try:
		close_facility(fac.name)
	except frappe.ValidationError as e:
		close_blocked = str(e)
	fac.reload()
	t7 = {"close_blocked_error": close_blocked, "remaining_total": flt(fac.remaining_total_amount)}
	results["tests"]["7_close_blocked"] = t7
	_log("Test 7 Close blocked", t7)
	if not close_blocked:
		errors.append("Test 7: close should fail with remaining balance")

	# Test 8 — Full payoff and close (pay remaining principal/profit)
	bal = get_facility_balance_row(fac)
	rep3 = frappe.new_doc("Facility Repayment")
	rep3.facility = fac.name
	rep3.posting_date = getdate(today())
	rep3.principal_amount = flt(bal["remaining_principal"])
	rep3.profit_amount = flt(bal["remaining_profit"])
	rep3.insert(ignore_permissions=True)
	rep3.submit()
	frappe.db.commit()
	fac.reload()
	close_facility(fac.name)
	fac.reload()
	t8 = {
		"final_repayment": rep3.name,
		"status": fac.status,
		"balance": get_facility_balance_row(fac),
	}
	results["tests"]["8_close_success"] = t8
	_log("Test 8 Close success", t8)
	if fac.status != "Closed":
		errors.append(f"Test 8: status {fac.status}")
	if flt(t8["balance"]["remaining_total"]) != 0:
		errors.append(f"Test 8: remaining {t8['balance']['remaining_total']}")

	# Test 9 — Opening facility Active without Receipt JE / no facility GL receipt
	open_fac = _new_facility(
		ctx,
		suffix=f"open-{suffix}",
		principal=principal,
		profit=profit,
		opening=True,
		status="Active",
		opening_paid_principal_amount=4_000_000_000.0,
		opening_paid_profit_amount=1_200_000_000.0,
	)
	gl_receipt = frappe.db.count(
		"GL Entry",
		{
			"is_cancelled": 0,
			"voucher_type": "Journal Entry",
			"company": ctx["company"],
			"remarks": ("like", f"%{open_fac.name}%"),
		},
	)
	t9 = {
		"facility": open_fac.name,
		"status": open_fac.status,
		"receipt_journal_entry": open_fac.receipt_journal_entry,
		"gl_entries_for_facility_receipt": gl_receipt,
	}
	results["tests"]["9_opening_no_receipt_je"] = t9
	_log("Test 9 Opening facility", t9)
	if open_fac.receipt_journal_entry:
		errors.append("Test 9: opening facility must not have receipt JE")
	if open_fac.status != "Active":
		errors.append("Test 9: opening must be Active")

	# Test 10 — Balance report
	cols, bal_data = balance_execute({"company": ctx["company"], "facility": open_fac.name})
	open_row = next((r for r in bal_data if r["facility"] == open_fac.name), None)
	t10 = {"columns": len(cols), "row": open_row}
	results["tests"]["10_balance_report"] = t10
	_log("Test 10 Facility Balance report", t10)
	if not open_row or flt(open_row["paid_principal"]) != 4_000_000_000.0:
		errors.append(f"Test 10: balance report row {open_row}")

	# Test 11 — Ledger opening row
	_, ledger_data = ledger_execute(
		{"company": ctx["company"], "facility": open_fac.name, "from_date": open_fac.contract_date}
	)
	t11 = {"ledger_rows": ledger_data}
	results["tests"]["11_facility_ledger"] = t11
	_log("Test 11 Facility Ledger", t11)
	opening_rows = [r for r in ledger_data if r.get("entry_type") == "Opening Balance"]
	if not opening_rows:
		errors.append("Test 11: missing Opening Balance row")
	elif flt(opening_rows[0]["principal_paid"]) != 4_000_000_000.0:
		errors.append(f"Test 11: opening principal paid {opening_rows[0]}")

	# Test 12 — Cancel repayment reverses JE link
	rep_open = frappe.new_doc("Facility Repayment")
	rep_open.facility = open_fac.name
	rep_open.posting_date = getdate(today())
	rep_open.principal_amount = 100_000_000.0
	rep_open.insert(ignore_permissions=True)
	rep_open.submit()
	je_before = rep_open.journal_entry
	rep_open.cancel()
	frappe.db.commit()
	je_docstatus = frappe.db.get_value("Journal Entry", je_before, "docstatus") if je_before else None
	t12 = {
		"repayment": rep_open.name,
		"cancelled_je": je_before,
		"je_docstatus": je_docstatus,
		"balance_after_cancel": get_facility_balance_row(open_fac),
	}
	results["tests"]["12_cancel_repayment"] = t12
	_log("Test 12 Cancel repayment", t12)
	if je_docstatus != 2:
		errors.append(f"Test 12: JE docstatus expected 2 (cancelled), got {je_docstatus}")

	results["errors"] = errors
	results["passed"] = not errors
	_log("SUMMARY", results)
	if errors:
		frappe.throw("Facility Management E2E failed:\n" + "\n".join(errors))
	print("\nFacility Management E2E Tests 1–12 PASSED")
	return results
