# Copyright (c) 2026, ERPNext Extensions contributors

from __future__ import annotations

import unittest
from decimal import Decimal
from unittest import mock

import frappe
from frappe.utils import flt, random_string, today

from erpnext_extensions.facility_management.doctype.facility.facility import (
	create_receipt_journal_entry,
	preview_receipt_journal_entry as preview_receipt_api,
)
from erpnext_extensions.facility_management.facility_accounting import (
	build_receipt_je_plan,
	build_repayment_je_plan,
	create_and_submit_receipt_je,
	create_and_submit_repayment_je,
	get_facility_dimension_fieldname,
	preview_receipt_journal_entry,
	preview_repayment_journal_entry,
	receipt_je_row_dimensions,
)
from erpnext_extensions.facility_management.facility_e2e_context import (
	apply_facility_test_accounts,
	ensure_bank_master,
)
from erpnext_extensions.facility_management.facility_settings_doc import get_facility_settings_doc, resolve_account


def _preview_rows_from_plan(plan) -> list[dict]:
	dim_fn = get_facility_dimension_fieldname()
	out = []
	for spec in plan:
		dims = spec.get("dims") or {}
		amount = spec["amount"]
		out.append(
			{
				"row_label": spec.get("row_label"),
				"account": spec["account"],
				"debit": float(amount) if spec["debit"] else 0,
				"credit": float(amount) if not spec["debit"] else 0,
				"user_remark": spec.get("user_remark") or "",
				"facility": dims.get(dim_fn) if dim_fn else None,
				"department": dims.get("department"),
				"cost_center": dims.get("cost_center"),
				"bank_dimension": dims.get("bank_dimension"),
				"bank_account_dimension": dims.get("bank_account_dimension"),
			}
		)
	return out


def _je_rows_for_compare(je_name: str) -> list[dict]:
	dim_fn = get_facility_dimension_fieldname()
	je = frappe.get_doc("Journal Entry", je_name)
	rows = []
	for row in je.accounts:
		rows.append(
			{
				"account": row.account,
				"debit": float(row.debit_in_account_currency or 0),
				"credit": float(row.credit_in_account_currency or 0),
				"facility": getattr(row, dim_fn, None) if dim_fn else None,
				"department": getattr(row, "department", None),
				"cost_center": getattr(row, "cost_center", None),
				"bank_dimension": getattr(row, "bank_dimension", None),
				"bank_account_dimension": getattr(row, "bank_account_dimension", None),
			}
		)
	return rows


def _new_receipt_facility(principal=8000, profit=1000):
	frappe.set_user("Administrator")
	company = frappe.db.get_value("Company", {}, "name", order_by="creation asc")
	bank = frappe.db.get_value("Bank", {}, "name", order_by="creation asc") or ensure_bank_master()
	fac = frappe.new_doc("Facility")
	fac.facility_name = f"JE Preview {random_string(5)}"
	fac.company = company
	fac.bank = bank
	fac.contract_date = today()
	fac.receive_date = today()
	fac.principal_amount = principal
	fac.profit_amount = profit
	apply_facility_test_accounts(fac)
	fac.insert(ignore_permissions=True)
	frappe.db.commit()
	return fac


class TestReceiptJePreview(unittest.TestCase):
	def test_receipt_preview_equals_submit_plan(self):
		frappe.set_user("Administrator")
		fac = _new_receipt_facility()
		plan = build_receipt_je_plan(fac)
		prev = preview_receipt_journal_entry(fac)
		self.assertEqual(len(prev["rows"]), len(plan))
		self.assertEqual(prev["rows"], _preview_rows_from_plan(plan))
		self.assertTrue(prev["balanced"])
		self.assertEqual(prev["total_debit"], prev["total_credit"])

	def test_receipt_preview_does_not_create_je(self):
		frappe.set_user("Administrator")
		fac = _new_receipt_facility()
		before = frappe.db.count("Journal Entry")
		preview_receipt_journal_entry(fac)
		self.assertEqual(frappe.db.count("Journal Entry"), before)
		self.assertFalse(fac.receipt_journal_entry)

	def test_receipt_preview_does_not_set_active(self):
		frappe.set_user("Administrator")
		fac = _new_receipt_facility()
		status_before = fac.status
		preview_receipt_journal_entry(fac)
		fac.reload()
		self.assertEqual(fac.status, status_before)
		self.assertFalse(fac.receipt_journal_entry)

	def test_receipt_preview_row_dimensions(self):
		frappe.set_user("Administrator")
		fac = _new_receipt_facility()
		settings = get_facility_settings_doc(fac.company)
		prev = preview_receipt_journal_entry(fac)
		by_label = {r["row_label"]: r for r in prev["rows"]}
		bank_dims = receipt_je_row_dimensions("bank", fac.name, facility=fac, settings=settings)
		self.assertEqual(by_label["Bank"]["bank_dimension"], bank_dims.get("bank_dimension"))
		dim_fn = get_facility_dimension_fieldname()
		if dim_fn:
			self.assertEqual(by_label["Deferred Loan Interest"]["facility"], fac.name)
			self.assertEqual(by_label["Loan Payable — Principal"]["facility"], fac.name)
			self.assertEqual(by_label["Loan Payable — Profit"]["facility"], fac.name)

	def test_receipt_four_row_split_amounts(self):
		frappe.set_user("Administrator")
		fac = _new_receipt_facility(principal=8000, profit=1000)
		plan = build_receipt_je_plan(fac)
		self.assertEqual(len(plan), 4)
		roles = [p["role"] for p in plan]
		self.assertEqual(roles, ["bank", "deferred", "loan_principal", "loan_profit"])
		self.assertEqual(float(plan[0]["amount"]), 8000.0)
		self.assertEqual(float(plan[1]["amount"]), 1000.0)
		self.assertTrue(plan[0]["debit"])
		self.assertTrue(plan[1]["debit"])
		self.assertFalse(plan[2]["debit"])
		self.assertFalse(plan[3]["debit"])
		self.assertEqual(float(plan[2]["amount"]), 8000.0)
		self.assertEqual(float(plan[3]["amount"]), 1000.0)
		self.assertEqual(plan[2]["account"], plan[3]["account"])
		prev = preview_receipt_journal_entry(fac)
		self.assertEqual(len(prev["rows"]), 4)
		self.assertEqual(prev["total_debit"], 9000.0)
		self.assertEqual(prev["total_credit"], 9000.0)

	def test_receipt_submitted_je_matches_preview(self):
		frappe.set_user("Administrator")
		fac = _new_receipt_facility()
		prev = preview_receipt_journal_entry(fac)
		je_name = create_and_submit_receipt_je(fac)
		je_rows = _je_rows_for_compare(je_name)
		for p_row, j_row in zip(prev["rows"], je_rows, strict=True):
			self.assertEqual(p_row["account"], j_row["account"])
			self.assertEqual(p_row["debit"], j_row["debit"])
			self.assertEqual(p_row["credit"], j_row["credit"])
			self.assertEqual(p_row.get("bank_dimension"), j_row.get("bank_dimension"))
			self.assertEqual(p_row.get("facility"), j_row.get("facility"))

	def test_receipt_preview_api_whitelist(self):
		frappe.set_user("Administrator")
		fac = _new_receipt_facility()
		out = preview_receipt_api(fac.name)
		self.assertTrue(out["balanced"])


class TestRepaymentJePreview(unittest.TestCase):
	def _draft_repayment(self):
		from erpnext_extensions.facility_management.e2e.facility_repayment_je_prep import prepare_active_facility

		prep = prepare_active_facility()
		rep = frappe.new_doc("Facility Repayment")
		rep.facility = prep["facility"]
		rep.posting_date = today()
		rep.principal_amount = 800
		rep.profit_amount = 140
		rep.penalty_amount = 60
		rep.insert(ignore_permissions=True)
		frappe.db.commit()
		return rep

	def test_repayment_preview_equals_submit_plan(self):
		frappe.set_user("Administrator")
		rep = self._draft_repayment()
		fac = frappe.get_doc("Facility", rep.facility)
		plan = build_repayment_je_plan(rep, facility=fac)
		prev = preview_repayment_journal_entry(rep)
		self.assertEqual(len(prev["rows"]), len(plan))
		self.assertEqual(prev["total_debit"], 1140.0)
		self.assertEqual(prev["total_credit"], 1140.0)
		self.assertTrue(prev["balanced"])

	def test_repayment_preview_does_not_create_je(self):
		frappe.set_user("Administrator")
		rep = self._draft_repayment()
		before = frappe.db.count("Journal Entry")
		preview_repayment_journal_entry(rep)
		self.assertEqual(frappe.db.count("Journal Entry"), before)

	def test_repayment_submitted_je_matches_preview(self):
		frappe.set_user("Administrator")
		rep = self._draft_repayment()
		prev = preview_repayment_journal_entry(rep)
		je_name = create_and_submit_repayment_je(rep)
		je_rows = _je_rows_for_compare(je_name)
		self.assertEqual(len(prev["rows"]), len(je_rows))
		for p_row, j_row in zip(prev["rows"], je_rows, strict=True):
			self.assertEqual(p_row["account"], j_row["account"])
			self.assertEqual(p_row["debit"], j_row["debit"])
			self.assertEqual(p_row["credit"], j_row["credit"])

	def test_preview_fails_missing_account_like_submit(self):
		frappe.set_user("Administrator")
		fac = _new_receipt_facility(profit=0)

		def fake_resolve(field, **kw):
			if field == "bank_account" and kw.get("required"):
				frappe.throw("Bank Account is required for Facility Receipt.", exc=frappe.ValidationError)
			return resolve_account(field, **kw)

		with mock.patch(
			"erpnext_extensions.facility_management.facility_accounting.resolve_account",
			side_effect=fake_resolve,
		):
			with self.assertRaises(frappe.ValidationError):
				preview_receipt_journal_entry(fac)


if __name__ == "__main__":
	unittest.main()
