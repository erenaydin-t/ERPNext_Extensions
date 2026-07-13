# Copyright (c) 2026, ERPNext Extensions contributors

from __future__ import annotations

import unittest

import frappe

from erpnext_extensions.facility_management.doctype.facility_repayment import facility_repayment as fr_mod
from erpnext_extensions.facility_management.e2e.facility_repayment_draft_override_prep import (
	REPAYMENT_ACCOUNTS_AND_DIMENSIONS,
	build_repayment_override_values,
	run_repayment_override_integration,
)
from erpnext_extensions.facility_management.e2e.facility_repayment_je_prep import prepare_active_facility
from erpnext_extensions.facility_management.facility_accounting import preview_repayment_journal_entry


class TestFacilityRepaymentFieldMeta(unittest.TestCase):
	def test_fetch_if_empty_on_accounts_and_dimensions(self):
		meta = frappe.get_meta("Facility Repayment")
		for fn in REPAYMENT_ACCOUNTS_AND_DIMENSIONS:
			df = meta.get_field(fn)
			self.assertIsNotNone(df, fn)
			self.assertEqual(cint(df.fetch_if_empty), 1, fn)
			self.assertTrue(df.fetch_from, fn)

	def test_submitted_docfields_not_allow_on_submit(self):
		meta = frappe.get_meta("Facility Repayment")
		for fn in REPAYMENT_ACCOUNTS_AND_DIMENSIONS:
			df = meta.get_field(fn)
			self.assertEqual(cint(df.allow_on_submit), 0, fn)


def cint(v):
	from frappe.utils import cint as _cint

	return _cint(v)


class TestFacilityRepaymentDraftOverrides(unittest.TestCase):
	def test_manual_override_not_cleared_on_validate(self):
		frappe.set_user("Administrator")
		prep = prepare_active_facility()
		fac = frappe.get_doc("Facility", prep["facility"])
		rep = frappe.new_doc("Facility Repayment")
		rep.facility = fac.name
		rep.posting_date = frappe.utils.today()
		rep.principal_amount = 100
		rep.profit_amount = 10
		rep.penalty_amount = 0
		overrides = build_repayment_override_values(fac.name)
		for fn, val in overrides.items():
			if fn in fr_mod._REPAYMENT_ACCOUNT_FIELDS:
				rep.set(fn, val)
		rep.insert(ignore_permissions=True)
		saved = {fn: rep.get(fn) for fn in fr_mod._REPAYMENT_ACCOUNT_FIELDS}
		rep.reload()
		rep.validate()
		for fn in fr_mod._REPAYMENT_ACCOUNT_FIELDS:
			if saved.get(fn):
				self.assertEqual(rep.get(fn), saved[fn], fn)

	def test_override_survives_reload(self):
		frappe.set_user("Administrator")
		prep = prepare_active_facility()
		overrides = build_repayment_override_values(prep["facility"])
		rep = frappe.new_doc("Facility Repayment")
		rep.facility = prep["facility"]
		rep.posting_date = frappe.utils.today()
		rep.principal_amount = 200
		rep.profit_amount = 20
		rep.penalty_amount = 5
		rep.interest_expense_account = overrides.get("interest_expense_account")
		rep.insert(ignore_permissions=True)
		rep.reload()
		self.assertEqual(rep.interest_expense_account, overrides.get("interest_expense_account"))

	def test_preview_uses_overridden_interest_account(self):
		frappe.set_user("Administrator")
		prep = prepare_active_facility()
		overrides = build_repayment_override_values(prep["facility"])
		rep = frappe.new_doc("Facility Repayment")
		rep.facility = prep["facility"]
		rep.posting_date = frappe.utils.today()
		rep.principal_amount = 0
		rep.profit_amount = 15
		rep.penalty_amount = 0
		for fn in fr_mod._REPAYMENT_ACCOUNT_FIELDS:
			if overrides.get(fn):
				rep.set(fn, overrides[fn])
		prev = preview_repayment_journal_entry(rep)
		int_row = next(r for r in prev["rows"] if r.get("row_label") == "Interest Expense")
		self.assertEqual(int_row["account"], rep.interest_expense_account)

	def test_override_survives_save_and_reload(self):
		frappe.set_user("Administrator")
		prep = prepare_active_facility()
		overrides = build_repayment_override_values(prep["facility"])
		rep = frappe.new_doc("Facility Repayment")
		rep.facility = prep["facility"]
		rep.posting_date = frappe.utils.today()
		rep.principal_amount = 150
		rep.profit_amount = 25
		rep.penalty_amount = 5
		for fn in REPAYMENT_ACCOUNTS_AND_DIMENSIONS:
			if overrides.get(fn):
				rep.set(fn, overrides[fn])
		rep.insert(ignore_permissions=True)
		rep.save(ignore_permissions=True)
		name = rep.name
		saved = {fn: rep.get(fn) for fn in REPAYMENT_ACCOUNTS_AND_DIMENSIONS}
		rep = frappe.get_doc("Facility Repayment", name)
		rep.validate()
		for fn in REPAYMENT_ACCOUNTS_AND_DIMENSIONS:
			if saved.get(fn):
				self.assertEqual(rep.get(fn), saved[fn], fn)

	def test_submitted_je_uses_overridden_bank_account(self):
		frappe.set_user("Administrator")
		result = run_repayment_override_integration()
		self.assertTrue(result["ok"], result)
		je = frappe.get_doc("Journal Entry", result["je"])
		bank = result["overrides"]["bank_account"]
		bank_rows = [r for r in je.accounts if r.account == bank]
		self.assertTrue(bank_rows, "Expected overridden bank account on submitted JE")


class TestFacilityRepaymentIntegration(unittest.TestCase):
	def test_full_override_integration(self):
		frappe.set_user("Administrator")
		out = run_repayment_override_integration()
		self.assertTrue(out["ok"], out)


if __name__ == "__main__":
	unittest.main()
