"""Prep Facility + Receipt JE for row-dimension browser E2E."""

from __future__ import annotations

import frappe
from frappe.utils import random_string, today

from erpnext_extensions.facility_management.doctype.facility.facility import create_receipt_journal_entry
from erpnext_extensions.facility_management.facility_accounting import get_facility_dimension_fieldname
from erpnext_extensions.facility_management.facility_settings_doc import get_facility_settings_doc


def _row_dims(row, dim_fn: str | None) -> dict:
	fields = ["department", "bank_dimension", "bank_account_dimension", "cost_center"]
	if dim_fn:
		fields.append(dim_fn)
	out = {}
	for fn in fields:
		if frappe.get_meta("Journal Entry Account").has_field(fn):
			val = getattr(row, fn, None)
			if val not in (None, ""):
				out[fn] = val
	return out


def prepare_receipt_je_with_dimensions():
	frappe.set_user("Administrator")
	company = frappe.db.get_value("Company", {}, "name", order_by="creation asc")
	settings = get_facility_settings_doc(company)
	bank = frappe.db.get_value("Bank", {}, "name", order_by="creation asc")
	bank_gl = (settings and settings.get("default_bank_account")) or frappe.db.get_value(
		"Account", {"company": company, "account_type": "Bank", "is_group": 0}, "name", order_by="creation asc"
	)
	loan = (settings and settings.get("default_loan_payable_account")) or None
	if not loan:
		for row in frappe.get_all(
			"Account",
			filters={"company": company, "root_type": "Liability", "is_group": 0},
			fields=["name", "account_type"],
			limit=30,
		):
			if (row.account_type or "") not in ("Payable", "Receivable"):
				loan = row.name
				break
	deferred = (settings and settings.get("default_deferred_loan_interest_account")) or frappe.db.get_value(
		"Account", {"company": company, "root_type": "Liability", "is_group": 0}, "name", order_by="creation asc"
	)
	dept = frappe.db.get_value("Department", {"company": company, "is_group": 0}, "name", order_by="creation asc")
	bank_dim = (settings and settings.get("default_bank_dimension")) or bank
	bank_acct_dim = (settings and settings.get("default_bank_account_dimension")) or frappe.db.get_value(
		"Bank Account", {"company": company}, "name", order_by="creation asc"
	)

	fac = frappe.new_doc("Facility")
	fac.facility_name = f"E2E Receipt JE Dim {random_string(5)}"
	fac.company = company
	fac.bank = bank
	fac.contract_date = today()
	fac.receive_date = today()
	fac.principal_amount = 2000
	fac.profit_amount = 200
	fac.bank_account = bank_gl
	fac.loan_payable_account = loan
	fac.deferred_loan_interest_account = deferred
	if dept:
		fac.department = dept
	if bank_dim:
		fac.bank_dimension = bank_dim
	if bank_acct_dim:
		fac.bank_account_dimension = bank_acct_dim
	fac.insert(ignore_permissions=True)
	frappe.db.commit()

	create_receipt_journal_entry(fac.name)
	fac.reload()
	dim_fn = get_facility_dimension_fieldname()
	je = frappe.get_doc("Journal Entry", fac.receipt_journal_entry)
	je_rows = []
	for row in je.accounts:
		je_rows.append(
			{
				"account": row.account,
				"debit": row.debit_in_account_currency,
				"credit": row.credit_in_account_currency,
				"dims": _row_dims(row, dim_fn),
			}
		)
	gl_fields = ["account", "debit", "credit", "department", "bank_dimension", "bank_account_dimension"]
	if dim_fn:
		gl_fields.append(dim_fn)
	gl_rows = frappe.get_all(
		"GL Entry",
		filters={"voucher_type": "Journal Entry", "voucher_no": fac.receipt_journal_entry, "is_cancelled": 0},
		fields=gl_fields,
		order_by="idx asc",
	)
	return {
		"facility": fac.name,
		"je": fac.receipt_journal_entry,
		"dim_fn": dim_fn,
		"bank_gl": bank_gl,
		"loan_gl": loan,
		"deferred_gl": deferred,
		"expected_bank_dimension": bank_dim,
		"je_rows": je_rows,
		"gl_rows": gl_rows,
	}
