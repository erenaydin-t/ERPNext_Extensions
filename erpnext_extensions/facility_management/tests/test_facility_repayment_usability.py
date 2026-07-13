# Copyright (c) 2026, ERPNext Extensions contributors

from __future__ import annotations

import unittest

import frappe

from erpnext_extensions.facility_management.facility_accounting import (
	build_repayment_je_plan,
	preview_repayment_journal_entry,
)
from erpnext_extensions.facility_management.facility_queries import (
	facility_link_query,
	facility_names_matching,
)
from erpnext_extensions.facility_management.facility_report_filters import apply_facility_filters_to_sql
from erpnext_extensions.facility_management.facility_settings_doc import resolve_account
from erpnext_extensions.facility_management.report.facility_balance.facility_balance import get_data


class TestInterestExpenseAccountField(unittest.TestCase):
	def test_doctype_has_interest_expense_account(self):
		meta = frappe.get_meta("Facility Repayment")
		self.assertTrue(meta.has_field("interest_expense_account"))
		df = meta.get_field("interest_expense_account")
		self.assertEqual(df.fieldtype, "Link")
		self.assertEqual(df.options, "Account")


class TestInterestAccountPriority(unittest.TestCase):
	def test_resolve_priority(self):
		class Rep:
			interest_expense_account = "REP-INT"

			def get(self, k, default=None):
				return getattr(self, k, default)

		class Fac:
			interest_expense_account = "FAC-INT"

			def get(self, k, default=None):
				return getattr(self, k, default)

		class Settings:
			default_interest_expense_account = "SET-INT"

			def get(self, k, default=None):
				return getattr(self, k, default)

		self.assertEqual(
			resolve_account("interest_expense_account", repayment=Rep(), facility=Fac(), settings=Settings()),
			"REP-INT",
		)
		self.assertEqual(
			resolve_account("interest_expense_account", repayment=None, facility=Fac(), settings=Settings()),
			"FAC-INT",
		)
		self.assertEqual(
			resolve_account("interest_expense_account", repayment=None, facility=None, settings=Settings()),
			"SET-INT",
		)


class TestFacilityNameSearch(unittest.TestCase):
	def test_link_query_by_facility_name(self):
		frappe.set_user("Administrator")
		company = frappe.db.get_value("Company", {}, "name", order_by="creation asc")
		if not company:
			self.skipTest("no company")
		marker = "تست سرچ FM"
		existing = frappe.db.get_value("Facility", {"facility_name": ["like", f"%{marker}%"]}, "name")
		if not existing:
			bank = frappe.db.get_value("Bank", {}, "name", order_by="creation asc")
			f = frappe.new_doc("Facility")
			f.facility_name = f"وام {marker} واحد"
			f.company = company
			f.bank = bank
			f.contract_date = frappe.utils.today()
			f.principal_amount = 100
			f.profit_amount = 0
			f.is_opening_facility = 1
			f.status = "Active"
			f.insert(ignore_permissions=True)
			frappe.db.commit()
			existing = f.name
		rows = facility_link_query("Facility", marker, "name", 0, 20, {})
		names = [r[0] for r in rows]
		self.assertIn(existing, names)

	def test_balance_report_facility_name_filter(self):
		frappe.set_user("Administrator")
		company = frappe.db.get_value("Company", {}, "name", order_by="creation asc")
		marker = "تست سرچ FM"
		names = facility_names_matching(company, marker)
		if not names:
			self.skipTest("no test facility")
		data = get_data({"company": company, "facility_name": marker})
		found = {r["facility"] for r in data}
		self.assertTrue(found.intersection(set(names)))


class TestPreviewUsesRepaymentInterestAccount(unittest.TestCase):
	def test_preview_interest_row_account(self):
		from erpnext_extensions.facility_management.e2e.facility_usability_prep import (
			prepare_usability_unit_facility,
		)
		from erpnext_extensions.facility_management.facility_settings_doc import get_facility_settings_doc

		frappe.set_user("Administrator")
		prep = prepare_usability_unit_facility()
		fac_doc = frappe.get_doc("Facility", prep["facility"])
		settings = get_facility_settings_doc(fac_doc.company)
		base = resolve_account("interest_expense_account", facility=fac_doc, settings=settings)
		self.assertTrue(base, "Facility must have interest_expense_account from settings")
		alt = frappe.db.get_value(
			"Account",
			{"company": fac_doc.company, "root_type": "Expense", "is_group": 0, "name": ("!=", base)},
			"name",
			order_by="modified desc",
		)
		rep = frappe.new_doc("Facility Repayment")
		rep.facility = fac_doc.name
		rep.posting_date = frappe.utils.today()
		rep.principal_amount = 0
		rep.profit_amount = 10
		rep.penalty_amount = 0
		rep.interest_expense_account = alt or base
		plan = build_repayment_je_plan(rep, facility=fac_doc)
		interest_rows = [p for p in plan if p.get("role") == "interest_expense"]
		self.assertEqual(len(interest_rows), 1)
		self.assertEqual(interest_rows[0]["account"], rep.interest_expense_account)
		prev = preview_repayment_journal_entry(rep)
		int_row = next(r for r in prev["rows"] if r.get("row_label") == "Interest Expense")
		self.assertEqual(int_row["account"], rep.interest_expense_account)


class TestLedgerFacilityNameFilter(unittest.TestCase):
	def test_ledger_filters_by_facility_name(self):
		from erpnext_extensions.facility_management.e2e.facility_usability_prep import prepare_search_facility
		from erpnext_extensions.facility_management.report.facility_ledger.facility_ledger import execute

		frappe.set_user("Administrator")
		prep = prepare_search_facility()
		_cols, data = execute(
			{
				"company": prep["company"],
				"facility_name": "سرمایه در گردش",
				"from_date": "2000-01-01",
				"to_date": frappe.utils.today(),
			}
		)
		self.assertGreaterEqual(len(data), 0)
		if data:
			self.assertEqual(data[0].get("facility"), prep["facility"])
