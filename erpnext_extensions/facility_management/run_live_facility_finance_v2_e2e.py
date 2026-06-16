"""Finance Excel model E2E — Facility Receipt & Repayment JE (development.localhost).

bench --site development.localhost execute \\
  erpnext_extensions.facility_management.run_live_facility_finance_v2_e2e.run
"""

from __future__ import annotations

import json
import time

import frappe
from frappe.utils import flt, today

from erpnext_extensions.facility_management.doctype.facility.facility import (
	close_facility,
	create_receipt_journal_entry,
)
from erpnext_extensions.facility_management.facility_accounting import get_facility_dimension_fieldname
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


def _ctx():
	frappe.set_user("Administrator")
	company = frappe.db.get_value("Company", {"name": ("!=", "")}, "name", order_by="creation asc")
	bank = frappe.db.get_value("Bank", {}, "name", order_by="modified desc")
	bank_gl = frappe.db.get_value(
		"Account", {"company": company, "account_type": "Bank", "is_group": 0}, "name", order_by="modified desc"
	)
	loan_payable = None
	deferred = frappe.db.get_value(
		"Account", {"company": company, "root_type": "Expense", "is_group": 0}, "name", order_by="modified desc"
	)
	penalty = frappe.db.get_value(
		"Account",
		{"company": company, "root_type": "Expense", "is_group": 0, "name": ("!=", deferred)},
		"name",
		order_by="modified desc",
	) or deferred
	for row in frappe.get_all(
		"Account",
		filters={"company": company, "root_type": "Liability", "is_group": 0},
		fields=["name", "account_type"],
		limit=50,
	):
		if (row.account_type or "") not in ("Payable", "Receivable"):
			loan_payable = row.name
			break
	if not all([company, bank, bank_gl, loan_payable, deferred]):
		frappe.throw("Missing accounts for Finance V2 E2E")
	return {
		"company": company,
		"bank": bank,
		"bank_gl": bank_gl,
		"loan_payable": loan_payable,
		"deferred": deferred,
		"penalty": penalty,
	}


def _debits_credits(je_name: str) -> tuple[dict[str, float], dict[str, float]]:
	je = frappe.get_doc("Journal Entry", je_name)
	dr: dict[str, float] = {}
	cr: dict[str, float] = {}
	for row in je.accounts:
		if flt(row.debit_in_account_currency):
			dr[row.account] = dr.get(row.account, 0) + flt(row.debit_in_account_currency)
		if flt(row.credit_in_account_currency):
			cr[row.account] = cr.get(row.account, 0) + flt(row.credit_in_account_currency)
	return dr, cr


def _row_remarks(je_name: str) -> list[str]:
	return [
		r.user_remark or ""
		for r in frappe.get_doc("Journal Entry", je_name).accounts
		if (r.user_remark or "").strip()
	]


def _ensure_settings(ctx, suffix: str):
	name = frappe.db.get_value("Facility Settings", {"company": ctx["company"]}, "name")
	if name:
		return frappe.get_doc("Facility Settings", name)
	doc = frappe.new_doc("Facility Settings")
	doc.company = ctx["company"]
	doc.default_bank_account = ctx["bank_gl"]
	doc.default_loan_payable_account = ctx["loan_payable"]
	doc.default_deferred_loan_interest_account = ctx["deferred"]
	doc.default_penalty_expense_account = ctx["penalty"]
	doc.insert(ignore_permissions=True)
	frappe.db.commit()
	return doc


def run():
	errors: list[str] = []
	results: dict = {"tests": {}}
	ctx = _ctx()
	dim_fn = get_facility_dimension_fieldname()
	suffix = str(int(time.time()))
	_ensure_settings(ctx, suffix)

	# Test A — Receipt Excel 8000 + 1000
	fac_a = frappe.new_doc("Facility")
	fac_a.facility_name = f"Finance V2 A {suffix}"
	fac_a.company = ctx["company"]
	fac_a.bank = ctx["bank"]
	fac_a.contract_date = today()
	fac_a.receive_date = today()
	fac_a.principal_amount = 8000
	fac_a.profit_amount = 1000
	fac_a.loan_payable_account = ctx["loan_payable"]
	fac_a.bank_account = ctx["bank_gl"]
	fac_a.deferred_loan_interest_account = ctx["deferred"]
	fac_a.interest_expense_account = ctx["interest"]
	fac_a.penalty_expense_account = ctx["penalty"]
	fac_a.insert(ignore_permissions=True)
	frappe.db.commit()
	create_receipt_journal_entry(fac_a.name)
	fac_a.reload()
	dr, cr = _debits_credits(fac_a.receipt_journal_entry)
	remarks = _row_remarks(fac_a.receipt_journal_entry)
	t_a = {
		"voucher_type": frappe.db.get_value("Journal Entry", fac_a.receipt_journal_entry, "voucher_type"),
		"dr_bank": dr.get(ctx["bank_gl"]),
		"dr_deferred": dr.get(ctx["deferred"]),
		"cr_loan": cr.get(ctx["loan_payable"]),
		"remarks": remarks,
	}
	results["tests"]["A_receipt_excel"] = t_a
	_log("Test A Receipt", t_a)
	if t_a["voucher_type"] != "Bank Entry":
		errors.append("A: voucher_type")
	if dr.get(ctx["bank_gl"]) != 8000 or dr.get(ctx["deferred"]) != 1000 or cr.get(ctx["loan_payable"]) != 9000:
		errors.append(f"A: amounts {t_a}")
	if not remarks or fac_a.name not in "".join(remarks):
		errors.append("A: row descriptions missing facility number")

	# Test B — Repayment Excel 800 + 140 + 60
	rep_b = frappe.new_doc("Facility Repayment")
	rep_b.facility = fac_a.name
	rep_b.posting_date = today()
	rep_b.principal_amount = 800
	rep_b.profit_amount = 140
	rep_b.penalty_amount = 60
	rep_b.insert(ignore_permissions=True)
	rep_b.submit()
	frappe.db.commit()
	dr, cr = _debits_credits(rep_b.journal_entry)
	t_b = {
		"voucher_type": frappe.db.get_value("Journal Entry", rep_b.journal_entry, "voucher_type"),
		"cr_bank": cr.get(ctx["bank_gl"]),
		"dr_loan": dr.get(ctx["loan_payable"]),
		"dr_deferred": dr.get(ctx["deferred"]),
		"dr_penalty": dr.get(ctx["penalty"]),
		"remarks": _row_remarks(rep_b.journal_entry),
	}
	results["tests"]["B_repayment_excel"] = t_b
	_log("Test B Repayment", t_b)
	if t_b["cr_bank"] != 1000:
		errors.append(f"B: bank cr {t_b}")
	loan_dr = dr.get(ctx["loan_payable"])
	if loan_dr != 940:
		errors.append(f"B: loan dr {loan_dr} expected 940 (800+140)")
	if dr.get(ctx["deferred"]):
		errors.append(f"B: deferred should be credit not debit {dr.get(ctx['deferred'])}")
	if dr.get(ctx["penalty"]) != 60:
		errors.append(f"B: penalty dr {dr.get(ctx['penalty'])}")
	interest_acc = frappe.db.get_value("Facility", fac_a.name, "interest_expense_account") or ctx.get(
		"interest"
	)
	if interest_acc and dr.get(interest_acc) != 140:
		errors.append(f"B: interest expense dr {dr.get(interest_acc)}")
	if cr.get(ctx["deferred"]) != 140:
		errors.append(f"B: deferred credit {cr.get(ctx['deferred'])}")

	# Test C — zero profit
	rep_c = frappe.new_doc("Facility Repayment")
	rep_c.facility = fac_a.name
	rep_c.posting_date = today()
	rep_c.principal_amount = 800
	rep_c.profit_amount = 0
	rep_c.penalty_amount = 60
	rep_c.insert(ignore_permissions=True)
	rep_c.submit()
	dr, cr = _debits_credits(rep_c.journal_entry)
	t_c = {"dr_deferred": dr.get(ctx["deferred"]), "cr_bank": cr.get(ctx["bank_gl"])}
	results["tests"]["C_zero_profit"] = t_c
	if t_c["dr_deferred"]:
		errors.append("C: unexpected deferred row")

	# Test D — zero penalty
	rep_d = frappe.new_doc("Facility Repayment")
	rep_d.facility = fac_a.name
	rep_d.posting_date = today()
	rep_d.principal_amount = 800
	rep_d.profit_amount = 140
	rep_d.penalty_amount = 0
	rep_d.insert(ignore_permissions=True)
	rep_d.submit()
	dr, _ = _debits_credits(rep_d.journal_entry)
	if dr.get(ctx["penalty"]):
		errors.append("D: unexpected penalty row")

	# Test E — all zero blocked
	try:
		z = frappe.new_doc("Facility Repayment")
		z.facility = fac_a.name
		z.posting_date = today()
		z.insert(ignore_permissions=True)
		z.submit()
		errors.append("E: should block")
	except Exception:
		frappe.db.rollback()

	# Test F — settings defaults (facility without explicit accounts)
	fac_f = frappe.new_doc("Facility")
	fac_f.facility_name = f"Finance V2 F {suffix}"
	fac_f.company = ctx["company"]
	fac_f.bank = ctx["bank"]
	fac_f.contract_date = today()
	fac_f.receive_date = today()
	fac_f.principal_amount = 500
	fac_f.profit_amount = 0
	fac_f.insert(ignore_permissions=True)
	frappe.db.commit()
	try:
		create_receipt_journal_entry(fac_f.name)
		fac_f.reload()
		if not fac_f.receipt_journal_entry:
			errors.append("F: receipt failed without facility accounts")
	except Exception as e:
		errors.append(f"F: {e}")

	# Test G — repayment override
	alt_bank = ctx["bank_gl"]
	rep_g = frappe.new_doc("Facility Repayment")
	rep_g.facility = fac_a.name
	rep_g.posting_date = today()
	rep_g.principal_amount = 10
	rep_g.bank_account = alt_bank
	rep_g.insert(ignore_permissions=True)
	rep_g.submit()
	_, cr = _debits_credits(rep_g.journal_entry)
	if cr.get(alt_bank) != 10:
		errors.append("G: override bank not used")

	# Test H — reports
	bal = get_facility_balance_row(fac_a.name)
	_, bal_rows = balance_execute({"company": ctx["company"], "facility": fac_a.name})
	bal_row = next((r for r in bal_rows if r.get("facility") == fac_a.name), {})
	results["tests"]["H_reports"] = {"service": bal, "report": bal_row}

	# Test I — settlement on close (pay down remaining on separate small facility)
	fac_i = frappe.new_doc("Facility")
	fac_i.facility_name = f"Finance V2 I {suffix}"
	fac_i.company = ctx["company"]
	fac_i.bank = ctx["bank"]
	fac_i.contract_date = today()
	fac_i.receive_date = today()
	fac_i.principal_amount = 100
	fac_i.profit_amount = 0
	fac_i.loan_payable_account = ctx["loan_payable"]
	fac_i.bank_account = ctx["bank_gl"]
	fac_i.insert(ignore_permissions=True)
	create_receipt_journal_entry(fac_i.name)
	r = frappe.new_doc("Facility Repayment")
	r.facility = fac_i.name
	r.posting_date = today()
	r.principal_amount = 100
	r.insert(ignore_permissions=True)
	r.submit()
	close_facility(fac_i.name)
	fac_i.reload()
	if not fac_i.settlement_date:
		errors.append("I: settlement_date missing after close")

	# Test J — opening repayment still uses model
	open_f = frappe.new_doc("Facility")
	open_f.facility_name = f"Finance V2 J {suffix}"
	open_f.company = ctx["company"]
	open_f.bank = ctx["bank"]
	open_f.contract_date = today()
	open_f.principal_amount = 1000
	open_f.profit_amount = 200
	open_f.loan_payable_account = ctx["loan_payable"]
	open_f.bank_account = ctx["bank_gl"]
	open_f.deferred_loan_interest_account = ctx["deferred"]
	open_f.is_opening_facility = 1
	open_f.status = "Active"
	open_f.insert(ignore_permissions=True)
	rep_j = frappe.new_doc("Facility Repayment")
	rep_j.facility = open_f.name
	rep_j.posting_date = today()
	rep_j.principal_amount = 100
	rep_j.profit_amount = 20
	rep_j.insert(ignore_permissions=True)
	rep_j.submit()
	if not rep_j.journal_entry:
		errors.append("J: opening repayment JE missing")

	results["errors"] = errors
	results["passed"] = not errors
	_log("SUMMARY", results)
	if errors:
		frappe.throw("Finance V2 E2E failed:\n" + "\n".join(errors))
	print("\nFacility Finance V2 E2E Tests A–J PASSED")
	return results
