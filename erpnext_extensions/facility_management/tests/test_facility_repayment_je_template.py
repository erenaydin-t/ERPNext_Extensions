# Copyright (c) 2026, ERPNext Extensions contributors

from __future__ import annotations

import unittest
from decimal import Decimal
from unittest import mock

import frappe
from frappe.utils import random_string, today

from erpnext_extensions.facility_management.doctype.facility.facility import create_receipt_journal_entry
from erpnext_extensions.facility_management.facility_accounting import (
	build_repayment_je_plan,
	create_and_submit_repayment_je,
	preview_repayment_journal_entry,
)
from erpnext_extensions.facility_management.facility_settings_doc import (
	get_facility_settings_doc,
	resolve_repayment_cost_center,
	validate_repayment_je_prerequisites,
)


class TestRepaymentJeTemplateUnit(unittest.TestCase):
	def test_full_template_amounts(self):
		class Fac:
			name = "FAC-X"
			company = "C"
			facility_name = "T"
			bank = "B"

			def get(self, k, default=None):
				return getattr(self, k, default)

		class Rep:
			facility = "FAC-X"
			company = "C"
			principal_amount = 800
			profit_amount = 140
			penalty_amount = 60

			def get(self, k, default=None):
				return getattr(self, k, default)

		with mock.patch(
			"erpnext_extensions.facility_management.facility_accounting.validate_repayment_je_prerequisites"
		), mock.patch(
			"erpnext_extensions.facility_management.facility_accounting.resolve_account",
			side_effect=lambda fn, **kw: {
				"bank_account": "BANK",
				"loan_payable_account": "LOAN",
				"deferred_loan_interest_account": "DEF",
				"interest_expense_account": "INT",
				"penalty_expense_account": "PEN",
			}.get(kw.get("fieldname") if "fieldname" in kw else fn, "ACC"),
		), mock.patch(
			"erpnext_extensions.facility_management.facility_accounting.get_facility_settings_doc",
			return_value=None,
		), mock.patch(
			"erpnext_extensions.facility_management.facility_accounting.repayment_je_row_dimensions",
			return_value={},
		), mock.patch(
			"erpnext_extensions.facility_management.facility_accounting.render_facility_template",
			side_effect=lambda t, c: t,
		), mock.patch(
			"erpnext_extensions.facility_management.facility_accounting.build_template_context",
			return_value={},
		), mock.patch(
			"erpnext_extensions.facility_management.facility_accounting._repayment_amounts",
			return_value=(Decimal("800"), Decimal("140"), Decimal("60")),
		):
			plan = build_repayment_je_plan(Rep(), facility=Fac())
		self.assertEqual(len(plan), 6)
		debits = sum(p["amount"] for p in plan if p["debit"])
		credits = sum(p["amount"] for p in plan if not p["debit"])
		self.assertEqual(debits, Decimal("1140"))
		self.assertEqual(credits, Decimal("1140"))


class TestRepaymentJeTemplateIntegration(unittest.TestCase):
	def _active_facility(self):
		frappe.set_user("Administrator")
		company = frappe.db.get_value("Company", {}, "name", order_by="creation asc")
		settings = get_facility_settings_doc(company)
		bank = frappe.db.get_value("Bank", {}, "name", order_by="creation asc")
		bank_gl = settings.get("default_bank_account") if settings else None
		loan = settings.get("default_loan_payable_account") if settings else None
		deferred = settings.get("default_deferred_loan_interest_account") if settings else None
		interest = settings.get("default_interest_expense_account") if settings else None
		penalty = settings.get("default_penalty_expense_account") if settings else None
		cc = resolve_repayment_cost_center(facility=None, settings=settings)
		fac = frappe.new_doc("Facility")
		fac.facility_name = f"Rep JE {random_string(5)}"
		fac.company = company
		fac.bank = bank
		fac.contract_date = today()
		fac.receive_date = today()
		fac.principal_amount = 10000
		fac.profit_amount = 2000
		fac.bank_account = bank_gl
		fac.loan_payable_account = loan
		fac.deferred_loan_interest_account = deferred
		fac.interest_expense_account = interest
		fac.penalty_expense_account = penalty
		if cc:
			fac.cost_center = cc
		fac.insert(ignore_permissions=True)
		frappe.db.commit()
		create_receipt_journal_entry(fac.name)
		fac.reload()
		return fac

	def test_submit_full_template(self):
		fac = self._active_facility()
		rep = frappe.new_doc("Facility Repayment")
		rep.facility = fac.name
		rep.posting_date = today()
		rep.principal_amount = 800
		rep.profit_amount = 140
		rep.penalty_amount = 60
		rep.insert(ignore_permissions=True)
		preview = preview_repayment_journal_entry(rep)
		self.assertTrue(preview["balanced"])
		self.assertEqual(preview["total_debit"], 1140.0)
		self.assertEqual(len(preview["rows"]), 6)
		rep.submit()
		frappe.db.commit()
		je = frappe.get_doc("Journal Entry", rep.journal_entry)
		self.assertEqual(je.voucher_type, "Bank Entry")
		self.assertEqual(len(je.accounts), 6)
		debits = sum(flt(r.debit_in_account_currency) for r in je.accounts)
		credits = sum(flt(r.credit_in_account_currency) for r in je.accounts)
		self.assertEqual(debits, 1140)
		self.assertEqual(credits, 1140)
		submit_preview = build_repayment_je_plan(rep, facility=fac)
		self.assertEqual(len(submit_preview), len(preview["rows"]))

	def test_profit_zero_skips_profit_rows(self):
		fac = self._active_facility()
		rep = frappe.new_doc("Facility Repayment")
		rep.facility = fac.name
		rep.posting_date = today()
		rep.principal_amount = 500
		rep.profit_amount = 0
		rep.penalty_amount = 0
		rep.insert(ignore_permissions=True)
		prev = preview_repayment_journal_entry(rep)
		self.assertEqual(len(prev["rows"]), 2)
		rep.submit()

	def test_penalty_zero(self):
		fac = self._active_facility()
		rep = frappe.new_doc("Facility Repayment")
		rep.facility = fac.name
		rep.posting_date = today()
		rep.principal_amount = 100
		rep.profit_amount = 0
		rep.penalty_amount = 0
		rep.insert(ignore_permissions=True)
		prev = preview_repayment_journal_entry(rep)
		labels = [r["row_label"] for r in prev["rows"]]
		self.assertFalse(any("Penalty" in (l or "") for l in labels))

	def test_missing_cost_center_blocked(self):
		fac = self._active_facility()
		rep = frappe.new_doc("Facility Repayment")
		rep.facility = fac.name
		rep.posting_date = today()
		rep.principal_amount = 0
		rep.profit_amount = 10
		rep.penalty_amount = 0
		settings = get_facility_settings_doc(fac.company)
		with mock.patch(
			"erpnext_extensions.facility_management.facility_settings_doc.resolve_repayment_cost_center",
			return_value=None,
		):
			with self.assertRaises(frappe.ValidationError):
				validate_repayment_je_prerequisites(
					rep,
					fac,
					settings,
					principal=0,
					profit=10,
					penalty=0,
				)


def flt(v):
	from frappe.utils import flt as _flt

	return _flt(v)
