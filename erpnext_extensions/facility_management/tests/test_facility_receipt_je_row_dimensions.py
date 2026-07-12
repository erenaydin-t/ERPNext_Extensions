# Copyright (c) 2026, ERPNext Extensions contributors

from __future__ import annotations

import unittest
from unittest import mock

import frappe
from frappe.utils import flt, random_string, today

from erpnext_extensions.facility_management.facility_accounting import (
	create_and_submit_receipt_je,
	get_facility_dimension_fieldname,
	receipt_je_row_dimensions,
)
from erpnext_extensions.facility_management.facility_e2e_context import (
	apply_facility_test_accounts,
	ensure_bank_master,
)
from erpnext_extensions.facility_management.facility_settings_doc import (
	_je_account_has_field,
	get_facility_settings_doc,
)


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

		with mock.patch(
			"erpnext_extensions.facility_management.facility_accounting._je_account_has_field",
			side_effect=lambda fn: fn == "bank_dimension",
		):
			bank_dims = receipt_je_row_dimensions("bank", "FAC-TEST", facility=Fac(), settings=None)
		self.assertEqual(bank_dims, {"bank_dimension": "BANK-DIM"})
		loan_dims = receipt_je_row_dimensions("loan_principal", "FAC-TEST", facility=Fac(), settings=None)
		fn = get_facility_dimension_fieldname()
		if fn:
			self.assertEqual(loan_dims.get(fn), "FAC-TEST")


class TestReceiptJeRowDimensionsIntegration(unittest.TestCase):
	def test_receipt_je_matches_finance_excel(self):
		frappe.set_user("Administrator")
		company = frappe.db.get_value("Company", {}, "name", order_by="creation asc")
		if not company:
			self.skipTest("No Company")
		bank = frappe.db.get_value("Bank", {}, "name", order_by="creation asc") or ensure_bank_master()
		dept = frappe.db.get_value(
			"Department", {"company": company, "is_group": 0}, "name", order_by="creation asc"
		)

		fac = frappe.new_doc("Facility")
		fac.facility_name = f"JE Dim {random_string(6)}"
		fac.company = company
		fac.bank = bank
		fac.contract_date = today()
		fac.receive_date = today()
		fac.principal_amount = 1000
		fac.profit_amount = 100
		apply_facility_test_accounts(fac)
		bank_gl = fac.bank_account
		loan = fac.loan_payable_account
		deferred = fac.deferred_loan_interest_account
		bank_dim = fac.bank_dimension
		bank_acct_dim = fac.bank_account_dimension
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
		bank_row = deferred_row = None
		loan_credit_rows = []
		for row in je.accounts:
			if row.account == bank_gl and row.debit_in_account_currency:
				bank_row = row
			elif row.account == deferred and row.debit_in_account_currency:
				deferred_row = row
			elif row.account == loan and row.credit_in_account_currency:
				loan_credit_rows.append(row)

		self.assertIsNotNone(bank_row, "bank debit row")
		self.assertIsNotNone(deferred_row, "deferred debit row")
		self.assertEqual(len(loan_credit_rows), 2, "two loan payable credit rows")
		self.assertEqual(
			sorted(flt(r.credit_in_account_currency) for r in loan_credit_rows),
			[100.0, 1000.0],
		)

		bank_dims = _je_row_dims(bank_row)
		if _je_account_has_field("bank_dimension") and (bank_dim or fac.bank_dimension):
			self.assertEqual(bank_dims.get("bank_dimension"), bank_dim or fac.bank_dimension)
		self.assertNotIn("department", bank_dims)
		self.assertNotIn("bank_account_dimension", bank_dims)
		if dim_fn:
			self.assertNotIn(dim_fn, bank_dims)

		for liability_row in (deferred_row, *loan_credit_rows):
			ld = _je_row_dims(liability_row)
			if dim_fn:
				self.assertEqual(ld.get(dim_fn), fac.name)
			self.assertNotIn("department", ld)
			self.assertNotIn("bank_dimension", ld)
			self.assertNotIn("bank_account_dimension", ld)

		gl_fields = ["account", "debit", "credit"]
		for fn in ("department", "bank_dimension", "bank_account_dimension"):
			if frappe.get_meta("GL Entry").has_field(fn):
				gl_fields.append(fn)
		if dim_fn and frappe.get_meta("GL Entry").has_field(dim_fn):
			gl_fields.append(dim_fn)
		gl = frappe.get_all(
			"GL Entry",
			filters={"voucher_type": "Journal Entry", "voucher_no": je_name, "is_cancelled": 0},
			fields=gl_fields,
			order_by="idx asc",
		)
		self.assertGreaterEqual(len(gl), 4)
		loan_gl_credits = []
		for entry in gl:
			if entry.account == bank_gl and frappe.utils.flt(entry.debit):
				if _je_account_has_field("bank_dimension") and (bank_dim or fac.bank_dimension):
					self.assertEqual(entry.bank_dimension, bank_dim or fac.bank_dimension)
				if dim_fn:
					self.assertFalse(entry.get(dim_fn))
			if entry.account == deferred and frappe.utils.flt(entry.debit):
				if dim_fn:
					self.assertEqual(entry.get(dim_fn), fac.name)
				if "department" in gl_fields:
					self.assertFalse(entry.department)
				if "bank_dimension" in gl_fields:
					self.assertFalse(entry.bank_dimension)
			if entry.account == loan and frappe.utils.flt(entry.credit):
				loan_gl_credits.append(frappe.utils.flt(entry.credit))
				if dim_fn:
					self.assertEqual(entry.get(dim_fn), fac.name)
				if "department" in gl_fields:
					self.assertFalse(entry.department)
				if "bank_dimension" in gl_fields:
					self.assertFalse(entry.bank_dimension)
		self.assertEqual(sorted(loan_gl_credits), [100.0, 1000.0])
