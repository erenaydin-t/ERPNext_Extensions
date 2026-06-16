# Copyright (c) 2026, ERPNext Extensions contributors

from __future__ import annotations

import unittest

import frappe
from frappe.utils import random_string, today

from erpnext_extensions.facility_management.facility_accounting import (
	create_and_submit_receipt_je,
	get_facility_dimension_fieldname,
	receipt_je_row_dimensions,
)
from erpnext_extensions.facility_management.facility_settings_doc import get_facility_settings_doc


def _je_row_dims(row) -> dict:
	dim_fn = get_facility_dimension_fieldname()
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


class TestReceiptJeRowDimensionsUnit(unittest.TestCase):
	def test_receipt_row_dimension_map(self):
		class Fac:
			name = "FAC-TEST"
			company = "C"
			bank_dimension = "BANK-DIM"

			def get(self, k):
				return getattr(self, k, None)

		bank_dims = receipt_je_row_dimensions("bank", "FAC-TEST", facility=Fac(), settings=None)
		self.assertEqual(bank_dims, {"bank_dimension": "BANK-DIM"})
		loan_dims = receipt_je_row_dimensions("loan", "FAC-TEST", facility=Fac(), settings=None)
		fn = get_facility_dimension_fieldname()
		if fn:
			self.assertEqual(loan_dims.get(fn), "FAC-TEST")


class TestReceiptJeRowDimensionsIntegration(unittest.TestCase):
	def test_receipt_je_matches_finance_excel(self):
		frappe.set_user("Administrator")
		company = frappe.db.get_value("Company", {}, "name", order_by="creation asc")
		if not company:
			self.skipTest("No Company")
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
		dept = frappe.db.get_value(
			"Department", {"company": company, "is_group": 0}, "name", order_by="creation asc"
		)
		bank_dim = settings.get("default_bank_dimension") if settings else bank
		bank_acct_dim = settings.get("default_bank_account_dimension") if settings else None
		if not bank_acct_dim:
			bank_acct_dim = frappe.db.get_value("Bank Account", {"company": company}, "name", order_by="creation asc")

		if not all([bank_gl, loan, deferred, bank]):
			self.skipTest("Missing accounts/bank for integration")

		fac = frappe.new_doc("Facility")
		fac.facility_name = f"JE Dim {random_string(6)}"
		fac.company = company
		fac.bank = bank
		fac.contract_date = today()
		fac.receive_date = today()
		fac.principal_amount = 1000
		fac.profit_amount = 100
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

		je_name = create_and_submit_receipt_je(fac)
		dim_fn = get_facility_dimension_fieldname()
		je = frappe.get_doc("Journal Entry", je_name)
		bank_row = deferred_row = loan_row = None
		for row in je.accounts:
			if row.account == bank_gl and row.debit_in_account_currency:
				bank_row = row
			elif row.account == deferred and row.debit_in_account_currency:
				deferred_row = row
			elif row.account == loan and row.credit_in_account_currency:
				loan_row = row

		self.assertIsNotNone(bank_row, "bank debit row")
		self.assertIsNotNone(deferred_row, "deferred debit row")
		self.assertIsNotNone(loan_row, "loan credit row")

		bank_dims = _je_row_dims(bank_row)
		self.assertEqual(bank_dims.get("bank_dimension"), bank_dim or fac.bank_dimension)
		self.assertNotIn("department", bank_dims)
		self.assertNotIn("bank_account_dimension", bank_dims)
		if dim_fn:
			self.assertNotIn(dim_fn, bank_dims)

		for liability_row in (deferred_row, loan_row):
			ld = _je_row_dims(liability_row)
			if dim_fn:
				self.assertEqual(ld.get(dim_fn), fac.name)
			self.assertNotIn("department", ld)
			self.assertNotIn("bank_dimension", ld)
			self.assertNotIn("bank_account_dimension", ld)

		gl = frappe.get_all(
			"GL Entry",
			filters={"voucher_type": "Journal Entry", "voucher_no": je_name, "is_cancelled": 0},
			fields=["account", "debit", "credit", "department", "bank_dimension", "bank_account_dimension"]
			+ ([dim_fn] if dim_fn else []),
			order_by="idx asc",
		)
		self.assertGreaterEqual(len(gl), 3)
		for entry in gl:
			if entry.account == bank_gl and frappe.utils.flt(entry.debit):
				self.assertTrue(entry.bank_dimension)
				if dim_fn:
					self.assertFalse(entry.get(dim_fn))
			if entry.account == deferred and frappe.utils.flt(entry.debit):
				if dim_fn:
					self.assertEqual(entry.get(dim_fn), fac.name)
				self.assertFalse(entry.department)
				self.assertFalse(entry.bank_dimension)
			if entry.account == loan and frappe.utils.flt(entry.credit):
				if dim_fn:
					self.assertEqual(entry.get(dim_fn), fac.name)
				self.assertFalse(entry.department)
				self.assertFalse(entry.bank_dimension)
