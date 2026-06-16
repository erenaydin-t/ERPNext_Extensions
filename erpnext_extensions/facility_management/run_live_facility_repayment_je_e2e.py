"""Live E2E: Facility Repayment JE (Bank Entry) — development.localhost.

bench --site development.localhost execute \\
  erpnext_extensions.facility_management.run_live_facility_repayment_je_e2e.run
"""

from __future__ import annotations

import json
import time

import frappe
from frappe.utils import flt

from erpnext_extensions.facility_management.facility_accounting import (
	get_facility_dimension_fieldname,
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


def _ctx():
	frappe.set_user("Administrator")
	company = frappe.db.get_value("Company", {"name": ("!=", "")}, "name", order_by="creation asc")
	bank = frappe.db.get_value("Bank", {}, "name", order_by="modified desc")
	bank_gl = frappe.db.get_value(
		"Account", {"company": company, "account_type": "Bank", "is_group": 0}, "name", order_by="modified desc"
	)
	loan_payable = None
	interest = frappe.db.get_value(
		"Account", {"company": company, "root_type": "Expense", "is_group": 0}, "name", order_by="modified desc"
	)
	penalty = frappe.db.get_value(
		"Account",
		{"company": company, "root_type": "Expense", "is_group": 0, "name": ("!=", interest)},
		"name",
		order_by="modified desc",
	)
	for row in frappe.get_all(
		"Account",
		filters={"company": company, "root_type": "Liability", "is_group": 0},
		fields=["name", "account_type"],
		limit=50,
	):
		if (row.account_type or "") not in ("Payable", "Receivable"):
			loan_payable = row.name
			break
	if not penalty:
		penalty = interest
	if not all([company, bank, bank_gl, loan_payable, interest]):
		frappe.throw("Missing test accounts")
	return {
		"company": company,
		"bank": bank,
		"bank_gl": bank_gl,
		"loan_payable": loan_payable,
		"deferred": interest,
		"interest": interest,
		"penalty": penalty,
	}


def _opening_facility(ctx, suffix: str, principal=10_000_000.0, profit=3_000_000.0):
	f = frappe.new_doc("Facility")
	f.facility_name = f"Rep JE E2E {suffix}"
	f.company = ctx["company"]
	f.bank = ctx["bank"]
	f.contract_date = frappe.utils.today()
	f.principal_amount = principal
	f.profit_amount = profit
	f.loan_payable_account = ctx["loan_payable"]
	f.bank_account = ctx["bank_gl"]
	f.deferred_loan_interest_account = ctx["deferred"]
	f.interest_expense_account = ctx.get("interest") or ctx["deferred"]
	f.penalty_expense_account = ctx["penalty"]
	f.is_opening_facility = 1
	f.status = "Active"
	f.insert(ignore_permissions=True)
	frappe.db.commit()
	return f


def _je_detail(je_name: str | None, dim_fn: str | None) -> dict:
	if not je_name:
		return {}
	je = frappe.get_doc("Journal Entry", je_name)
	rows = []
	for row in je.accounts:
		item = {
			"account": row.account,
			"debit": flt(row.debit_in_account_currency),
			"credit": flt(row.credit_in_account_currency),
		}
		if dim_fn:
			item[dim_fn] = getattr(row, dim_fn, None)
		rows.append(item)
	gl = frappe.get_all(
		"GL Entry",
		filters={"voucher_type": "Journal Entry", "voucher_no": je_name, "is_cancelled": 0},
		fields=["account", "debit", "credit", dim_fn] if dim_fn else ["account", "debit", "credit"],
		order_by="idx asc",
	)
	return {"voucher_type": je.voucher_type, "name": je.name, "je_rows": rows, "gl_rows": gl}


def _submit_rep(facility_name: str, *, principal=0, profit=0, penalty=0):
	rep = frappe.new_doc("Facility Repayment")
	rep.facility = facility_name
	rep.posting_date = frappe.utils.today()
	rep.principal_amount = principal
	rep.profit_amount = profit
	rep.penalty_amount = penalty
	rep.insert(ignore_permissions=True)
	rep.submit()
	frappe.db.commit()
	rep.reload()
	return rep


def _debits_by_account(je_rows: list[dict]) -> dict[str, float]:
	out: dict[str, float] = {}
	for r in je_rows:
		if flt(r.get("debit")):
			out[r["account"]] = out.get(r["account"], 0) + flt(r["debit"])
	return out


def _credit_bank(je_rows: list[dict]) -> float:
	return sum(flt(r.get("credit")) for r in je_rows)


def _je_amount_rows_exact(je_name: str) -> list[dict]:
	return frappe.db.sql(
		"""
		SELECT account,
			CAST(debit_in_account_currency AS CHAR) AS debit,
			CAST(credit_in_account_currency AS CHAR) AS credit
		FROM `tabJournal Entry Account`
		WHERE parent = %s
		ORDER BY idx ASC
		""",
		(je_name,),
		as_dict=True,
	)


def run():
	frappe.set_user("Administrator")
	errors: list[str] = []
	results: dict = {"tests": {}}
	ctx = _ctx()
	dim_fn = get_facility_dimension_fieldname()
	suffix = str(int(time.time()))
	fac = _opening_facility(ctx, suffix)

	# Test 1 — desk amounts (2M + 1500 + 200) save draft then submit
	rep_save = frappe.new_doc("Facility Repayment")
	rep_save.facility = fac.name
	rep_save.posting_date = frappe.utils.today()
	rep_save.principal_amount = 2_000_000
	rep_save.profit_amount = 1_500
	rep_save.penalty_amount = 200
	rep_save.insert(ignore_permissions=True)
	frappe.db.commit()
	db_total = flt(frappe.db.get_value("Facility Repayment", rep_save.name, "total_payment_amount"))
	t1b = {
		"repayment": rep_save.name,
		"total_payment_amount_after_insert": db_total,
	}
	if db_total != 2_001_700:
		errors.append(f"Test 1 save total: {db_total} expected 2001700")
	rep_save.submit()
	frappe.db.commit()
	d1 = _je_detail(rep_save.journal_entry, dim_fn)
	debits = _debits_by_account(d1["je_rows"])
	cr = _credit_bank(d1["je_rows"])
	t1 = {
		"repayment": rep_save.name,
		"total_payment_amount_after_insert": db_total,
		"je": d1,
		"loan_dr": debits.get(ctx["loan_payable"]),
		"interest_dr": debits.get(ctx["interest"]),
		"penalty_dr": debits.get(ctx["penalty"]),
		"bank_cr": cr,
	}
	results["tests"]["1_principal_profit_penalty"] = t1
	_log("Test 1 desk save + JE (2M+1500+200)", t1)
	if d1.get("voucher_type") != "Bank Entry":
		errors.append(f"Test 1: voucher_type {d1.get('voucher_type')}")
	if debits.get(ctx["loan_payable"]) != 2_001_500:
		errors.append(f"Test 1: loan dr {debits.get(ctx['loan_payable'])} (principal+profit)")
	if debits.get(ctx["deferred"]):
		errors.append(f"Test 1: deferred must be credit not debit {debits.get(ctx['deferred'])}")
	interest_acc = frappe.db.get_value("Facility", fac.name, "interest_expense_account")
	if interest_acc and debits.get(interest_acc) != 1_500:
		errors.append(f"Test 1: interest expense dr {debits.get(interest_acc)}")
	if debits.get(ctx["penalty"]) != 200:
		errors.append(f"Test 1: penalty dr {debits.get(ctx['penalty'])}")
	if cr != 2_001_700:
		errors.append(f"Test 1: bank cr {cr}")
	from erpnext_extensions.facility_management.facility_accounting import _validate_repayment_je_dimensions

	try:
		_validate_repayment_je_dimensions(rep_save.journal_entry, fac, rep_save)
	except Exception as e:
		errors.append(f"Test 1 Excel dims: {e}")

	# Test 6 reports (after Test 1 repayment only)
	bal1 = get_facility_balance_row(fac.name)
	_, bal_rows = balance_execute({"company": ctx["company"], "facility": fac.name})
	bal_row = next((r for r in bal_rows if r["facility"] == fac.name), {})
	_, ledger = ledger_execute(
		{"company": ctx["company"], "facility": fac.name, "from_date": fac.contract_date}
	)
	rep_rows = [r for r in ledger if r.get("entry_type") == "Facility Repayment"]
	t6 = {
		"balance_service": {
			"paid_principal": bal1["paid_principal"],
			"paid_profit": bal1["paid_profit"],
			"paid_penalty": bal1["paid_penalty"],
		},
		"balance_report": {
			"paid_principal": bal_row.get("paid_principal"),
			"paid_profit": bal_row.get("paid_profit"),
			"paid_penalty": bal_row.get("paid_penalty"),
		},
		"ledger_repayment_rows": len(rep_rows),
	}
	results["tests"]["6_reports_after_test1"] = t6
	_log("Test 6 reports after Test 1", t6)
	if flt(bal1["paid_principal"]) != 2_000_000 or flt(bal1["paid_profit"]) != 1_500 or flt(bal1["paid_penalty"]) != 200:
		errors.append(f"Test 6: balance mismatch {bal1}")

	# Test 2 — principal only (2M to match user scenario pattern)
	rep2 = _submit_rep(fac.name, principal=2_000_000, profit=0, penalty=0)
	d2 = _je_detail(rep2.journal_entry, dim_fn)
	debits2 = _debits_by_account(d2["je_rows"])
	t2 = {"repayment": rep2.name, "je": d2, "row_count": len(d2["je_rows"])}
	results["tests"]["2_principal_only"] = t2
	_log("Test 2 principal only", t2)
	if len(d2["je_rows"]) != 2:
		errors.append(f"Test 2: expected 2 rows, got {len(d2['je_rows'])}")
	if debits2.get(ctx["deferred"]):
		errors.append("Test 2: unexpected deferred interest row")
	if debits2.get(ctx["penalty"]):
		errors.append("Test 2: unexpected penalty row")
	if _credit_bank(d2["je_rows"]) != 2_000_000:
		errors.append(f"Test 2: bank cr {_credit_bank(d2['je_rows'])}")

	# Test 3
	rep3 = _submit_rep(fac.name, principal=0, profit=1_500, penalty=0)
	d3 = _je_detail(rep3.journal_entry, dim_fn)
	debits3 = _debits_by_account(d3["je_rows"])
	t3 = {"repayment": rep3.name, "je": d3}
	results["tests"]["3_profit_only"] = t3
	_log("Test 3 profit only", t3)
	if debits3.get(ctx["loan_payable"]):
		errors.append("Test 3: unexpected loan row")
	if debits3.get(ctx["deferred"]):
		errors.append("Test 3: unexpected deferred debit row")
	interest_acc = frappe.db.get_value("Facility", fac.name, "interest_expense_account")
	if interest_acc and debits3.get(interest_acc) != 1_500:
		errors.append(f"Test 3: interest expense {debits3.get(interest_acc)}")
	if _credit_bank(d3["je_rows"]) != 1_500:
		errors.append(f"Test 3: bank cr {_credit_bank(d3['je_rows'])}")

	# Test 4
	rep4 = _submit_rep(fac.name, principal=0, profit=0, penalty=200)
	d4 = _je_detail(rep4.journal_entry, dim_fn)
	debits4 = _debits_by_account(d4["je_rows"])
	t4 = {"repayment": rep4.name, "je": d4}
	results["tests"]["4_penalty_only"] = t4
	_log("Test 4 penalty only", t4)
	if debits4.get(ctx["penalty"]) != 200:
		errors.append(f"Test 4: penalty {debits4.get(ctx['penalty'])}")
	if _credit_bank(d4["je_rows"]) != 200:
		errors.append(f"Test 4: bank cr {_credit_bank(d4['je_rows'])}")

	# Test 5
	blocked = None
	try:
		rep5 = frappe.new_doc("Facility Repayment")
		rep5.facility = fac.name
		rep5.posting_date = frappe.utils.today()
		rep5.principal_amount = 0
		rep5.profit_amount = 0
		rep5.penalty_amount = 0
		rep5.insert(ignore_permissions=True)
		rep5.submit()
	except Exception as e:
		blocked = str(e)
	frappe.db.rollback()
	t5 = {"blocked": blocked}
	results["tests"]["5_zero_all"] = t5
	_log("Test 5 zero all blocked", t5)
	if not blocked:
		errors.append("Test 5: submit should be blocked")

	# Test 7 — DECIMAL(30,9) precision regression on save + JE
	from decimal import Decimal

	from erpnext_extensions.facility_management.facility_monetary import (
		get_exact_currency_char,
		parse_facility_amount,
	)
	from erpnext_extensions.patches.post_model_sync.expand_currency_precision import (
		execute as expand_je_precision,
	)
	from erpnext_extensions.patches.post_model_sync.expand_gl_entry_amount_precision import (
		execute as expand_gl_precision,
	)

	expand_je_precision()
	expand_gl_precision()
	frappe.db.commit()

	fac_prec = _opening_facility(ctx, f"prec-{suffix}", principal=1e15, profit=1e15)
	P = Decimal("1234567890123.123456789")
	Pr = Decimal("987654321234.123456789")
	Pn = Decimal("1.123456789")
	rep_prec = frappe.new_doc("Facility Repayment")
	rep_prec.facility = fac_prec.name
	rep_prec.posting_date = frappe.utils.today()
	rep_prec.principal_amount = str(P)
	rep_prec.profit_amount = str(Pr)
	rep_prec.penalty_amount = str(Pn)
	rep_prec.flags.facility_exact_currency = {
		"principal_amount": str(P),
		"profit_amount": str(Pr),
		"penalty_amount": str(Pn),
	}
	rep_prec.insert(ignore_permissions=True)
	frappe.db.commit()
	exp_total = P + Pr + Pn
	db_p = get_exact_currency_char("Facility Repayment", rep_prec.name, "principal_amount")
	db_total_prec = parse_facility_amount(
		get_exact_currency_char("Facility Repayment", rep_prec.name, "total_payment_amount")
	)
	rep_prec.submit()
	frappe.db.commit()
	je_rows_exact = _je_amount_rows_exact(rep_prec.journal_entry)
	je_principal_exact = any(parse_facility_amount(r["debit"]) == P for r in je_rows_exact)
	je_bank_exact = any(parse_facility_amount(r["credit"]) == exp_total for r in je_rows_exact)
	t7p = {
		"repayment": rep_prec.name,
		"db_principal_char": db_p,
		"db_total": str(db_total_prec),
		"expected_total": str(exp_total),
		"je_principal_exact": je_principal_exact,
		"je_bank_credit_exact": je_bank_exact,
	}
	results["tests"]["7_precision_regression"] = t7p
	_log("Test 7 precision regression", t7p)
	if parse_facility_amount(db_p) != P:
		errors.append(f"Test 7: principal db {db_p}")
	if db_total_prec != exp_total:
		errors.append(f"Test 7: total {db_total_prec} vs {exp_total}")
	if not je_principal_exact or not je_bank_exact:
		errors.append("Test 7: JE amounts not exact DECIMAL")

	# Test 8 cancel rep4
	je_to_cancel = rep4.journal_entry
	rep4.cancel()
	frappe.db.commit()
	je_st = frappe.db.get_value("Journal Entry", je_to_cancel, "docstatus") if je_to_cancel else None
	bal_after = get_facility_balance_row(fac.name)
	t7 = {"cancelled_je": je_to_cancel, "je_docstatus": je_st, "balance": bal_after}
	results["tests"]["8_cancel"] = t7
	_log("Test 8 cancel", t7)
	if je_st != 2:
		errors.append(f"Test 8: je docstatus {je_st}")

	results["errors"] = errors
	results["passed"] = not errors
	_log("SUMMARY", results)
	if errors:
		frappe.throw("Facility Repayment JE E2E failed:\n" + "\n".join(errors))
	print("\nFacility Repayment JE E2E Tests 1–8 PASSED")
	return results
