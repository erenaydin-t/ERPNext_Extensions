# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

"""Live E2E: Receipt JE split (4 rows) — development.localhost.

Run:
  cd /workspace/development/frappe-bench && bench --site development.localhost execute \\
    erpnext_extensions.facility_management.run_live_facility_receipt_split_e2e.run
"""

from __future__ import annotations

import json
import time

import frappe
from frappe.utils import flt, getdate, today

from erpnext_extensions.facility_management.doctype.facility.facility import create_receipt_journal_entry
from erpnext_extensions.facility_management.facility_accounting import (
	get_facility_dimension_fieldname,
	preview_receipt_journal_entry,
)
from erpnext_extensions.facility_management.facility_accounting_dimensions import (
	provision_facility_accounting_dimension,
)
from erpnext_extensions.facility_management.facility_e2e_context import (
	apply_facility_test_accounts,
	site_e2e_context,
)

PRINCIPAL = 6_340_000_000.0
PROFIT = 156_795_689.0


def _log(title: str, payload) -> None:
	print(f"\n=== {title} ===")
	print(json.dumps(payload, indent=2, default=str))


def _je_account_rows(je_name: str) -> list[dict]:
	return frappe.get_all(
		"Journal Entry Account",
		filters={"parent": je_name},
		fields=["idx", "account", "debit_in_account_currency", "credit_in_account_currency", "user_remark"],
		order_by="idx asc",
	)


def _gl_rows(je_name: str) -> list[dict]:
	return frappe.get_all(
		"GL Entry",
		filters={"voucher_type": "Journal Entry", "voucher_no": je_name, "is_cancelled": 0},
		fields=["idx", "account", "debit", "credit"],
		order_by="idx asc",
	)


def _preview_rows_for_compare(preview: dict) -> list[dict]:
	return [
		{
			"account": r["account"],
			"debit": flt(r.get("debit")),
			"credit": flt(r.get("credit")),
		}
		for r in preview.get("rows") or []
	]


def _je_rows_for_compare(je_name: str) -> list[dict]:
	out = []
	for row in frappe.get_doc("Journal Entry", je_name).accounts:
		out.append(
			{
				"account": row.account,
				"debit": flt(row.debit_in_account_currency),
				"credit": flt(row.credit_in_account_currency),
			}
		)
	return out


def run() -> dict:
	errors: list[str] = []
	results: dict = {}
	ctx = site_e2e_context()
	provision_facility_accounting_dimension()
	frappe.db.commit()
	dim_fn = get_facility_dimension_fieldname()
	suffix = str(int(time.time()))

	fac = frappe.new_doc("Facility")
	fac.facility_name = f"Receipt Split E2E {suffix}"
	fac.company = ctx["company"]
	fac.contract_date = getdate(today())
	fac.receive_date = getdate(today())
	fac.principal_amount = PRINCIPAL
	fac.profit_amount = PROFIT
	apply_facility_test_accounts(fac)
	fac.insert(ignore_permissions=True)
	frappe.db.commit()

	preview = preview_receipt_journal_entry(fac)
	if len(preview.get("rows") or []) != 4:
		errors.append(f"Preview expected 4 rows, got {len(preview.get('rows') or [])}")
	if not preview.get("balanced"):
		errors.append("Preview not balanced")
	if flt(preview.get("total_debit")) != PRINCIPAL + PROFIT:
		errors.append("Preview total debit mismatch")
	if flt(preview.get("total_credit")) != PRINCIPAL + PROFIT:
		errors.append("Preview total credit mismatch")

	out = create_receipt_journal_entry(fac.name)
	fac.reload()
	je_name = fac.receipt_journal_entry
	meta = frappe.db.get_value(
		"Journal Entry", je_name, ["voucher_type", "docstatus"], as_dict=True
	)
	if meta.voucher_type != "Bank Entry":
		errors.append(f"voucher_type {meta.voucher_type}")
	if meta.docstatus != 1:
		errors.append(f"docstatus {meta.docstatus}")

	je_rows = _je_account_rows(je_name)
	gl_rows = _gl_rows(je_name)
	if len(je_rows) != 4:
		errors.append(f"JE Account expected 4 rows, got {len(je_rows)}")
	if len(gl_rows) != 4:
		errors.append(f"GL Entry expected 4 rows, got {len(gl_rows)}")

	loan_acc = fac.loan_payable_account
	bank_acc = fac.bank_account
	deferred_acc = fac.deferred_loan_interest_account
	loan_credits = [r for r in je_rows if r.account == loan_acc and flt(r.credit_in_account_currency)]
	if len(loan_credits) != 2:
		errors.append(f"Expected 2 Loan Payable credits, got {len(loan_credits)}")
	loan_credit_amounts = sorted(flt(r.credit_in_account_currency) for r in loan_credits)
	if loan_credit_amounts != sorted([PRINCIPAL, PROFIT]):
		errors.append(f"Loan credit amounts {loan_credit_amounts}")
	combined = [r for r in je_rows if r.account == loan_acc and flt(r.credit_in_account_currency) == PRINCIPAL + PROFIT]
	if combined:
		errors.append("Aggregated principal+profit loan credit row still present")

	bank_dr = sum(flt(r.debit_in_account_currency) for r in je_rows if r.account == bank_acc)
	def_dr = sum(flt(r.debit_in_account_currency) for r in je_rows if r.account == deferred_acc)
	if bank_dr != PRINCIPAL:
		errors.append(f"Bank debit {bank_dr} != {PRINCIPAL}")
	if def_dr != PROFIT:
		errors.append(f"Deferred debit {def_dr} != {PROFIT}")

	gl_loan = sorted(flt(r.credit) for r in gl_rows if r.account == loan_acc and flt(r.credit))
	if gl_loan != sorted([PRINCIPAL, PROFIT]):
		errors.append(f"GL loan credits {gl_loan}")

	preview_cmp = _preview_rows_for_compare(preview)
	je_cmp = _je_rows_for_compare(je_name)
	if preview_cmp != je_cmp:
		errors.append("Preview rows != submitted JE rows")

	result = {
		"ok": not errors,
		"errors": errors,
		"facility": fac.name,
		"journal_entry": je_name,
		"principal": PRINCIPAL,
		"profit": PROFIT,
		"preview": preview,
		"journal_entry_meta": meta,
		"tabJournal Entry Account": je_rows,
		"tabGL Entry": gl_rows,
		"preview_equals_je": preview_cmp == je_cmp,
		"dimension_field": dim_fn,
	}
	_log("Receipt split E2E", result)
	results["high_value_receipt"] = result

	# Profit = 0 → 2-row receipt (bank + single loan principal credit)
	fac0 = frappe.new_doc("Facility")
	fac0.facility_name = f"Receipt Split Zero Profit {suffix}"
	fac0.company = ctx["company"]
	fac0.contract_date = getdate(today())
	fac0.receive_date = getdate(today())
	fac0.principal_amount = 1_000_000.0
	fac0.profit_amount = 0
	apply_facility_test_accounts(fac0)
	fac0.insert(ignore_permissions=True)
	frappe.db.commit()
	prev0 = preview_receipt_journal_entry(fac0)
	if len(prev0.get("rows") or []) != 2:
		errors.append(f"Profit=0 preview expected 2 rows, got {len(prev0.get('rows') or [])}")
	create_receipt_journal_entry(fac0.name)
	fac0.reload()
	je0_rows = _je_account_rows(fac0.receipt_journal_entry)
	if len(je0_rows) != 2:
		errors.append(f"Profit=0 JE expected 2 rows, got {len(je0_rows)}")
	loan_credits0 = [r for r in je0_rows if flt(r.credit_in_account_currency)]
	if len(loan_credits0) != 1:
		errors.append("Profit=0 expected one loan credit row")
	results["profit_zero"] = {
		"facility": fac0.name,
		"preview_rows": len(prev0.get("rows") or []),
		"je_rows": len(je0_rows),
	}

	if errors:
		frappe.throw("Receipt split E2E failed:\n" + "\n".join(errors))
	return results
