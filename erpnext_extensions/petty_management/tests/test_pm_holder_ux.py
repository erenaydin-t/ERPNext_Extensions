# Copyright (c) 2026, Farbod Siyahpoosh and contributors
"""PM Holder / PM Opening Advance link labels and search UX."""

from __future__ import annotations

import unittest

import frappe
from frappe.desk.search import search_link
from frappe.utils import today

from erpnext_extensions.petty_management.doctype.pm_holder.pm_holder import pm_holder_query
from erpnext_extensions.petty_management.doctype.pm_opening_advance.pm_opening_advance import (
	pm_opening_advance_link_query,
)
from erpnext_extensions.petty_management.services.holder_display import (
	format_pm_holder_search_employee_line,
	format_pm_holder_title,
)
from erpnext_extensions.petty_management.services.opening_advance_service import (
	format_opening_advance_link_search_row,
	pm_opening_advance_query_for_pm_clearance,
)
import erpnext_extensions.petty_management.tests.test_pm_clearance as pm_ct


class TestPMHolderUX(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")
		pm_ct._ensure_company_context()
		if not pm_ct.COMPANY:
			raise unittest.SkipTest("No Company on site")
		pm_ct._ensure_petty_account()

	def test_format_pm_holder_title(self):
		self.assertEqual(format_pm_holder_title("فربد ابراهیمی", "HR-EMP-00002"), "فربد ابراهیمی (HR-EMP-00002)")

	def test_pm_holder_document_get_title(self):
		emp = pm_ct._make_employee()
		holder_name = pm_ct._make_holder(emp)
		doc = frappe.get_doc("PM Holder", holder_name)
		employee_name = frappe.db.get_value("Employee", emp, "employee_name") or doc.employee_name
		expected = format_pm_holder_title(employee_name, emp)
		self.assertEqual(doc.get_title(), expected)

	def test_pm_holder_query_by_employee_code(self):
		emp = pm_ct._make_employee()
		holder_name = pm_ct._make_holder(emp)
		rows = pm_holder_query("PM Holder", emp, "name", 0, 20, {"company": pm_ct.COMPANY})
		names = {r[0] for r in rows}
		self.assertIn(holder_name, names)
		match = next(r for r in rows if r[0] == holder_name)
		self.assertEqual(len(match), 3)
		employee_name = frappe.db.get_value("Employee", emp, "employee_name")
		self.assertEqual(match[1], format_pm_holder_title(employee_name, emp, holder_name))

	def test_pm_holder_query_by_employee_name(self):
		emp = pm_ct._make_employee()
		holder_name = pm_ct._make_holder(emp)
		employee_name = (frappe.db.get_value("Employee", emp, "employee_name") or "").strip()
		if not employee_name or len(employee_name) < 2:
			raise unittest.SkipTest("Employee name too short for name search")
		needle = employee_name[: max(3, len(employee_name) // 2)]
		rows = pm_holder_query("PM Holder", needle, "name", 0, 50, {"company": pm_ct.COMPANY})
		names = {r[0] for r in rows}
		self.assertIn(holder_name, names)

	def test_search_link_pm_holder_by_employee_name(self):
		emp = pm_ct._make_employee()
		holder_name = pm_ct._make_holder(emp)
		employee_name = (frappe.db.get_value("Employee", emp, "employee_name") or "").strip()
		if not employee_name:
			raise unittest.SkipTest("No employee_name on Employee")
		results = search_link(
			doctype="PM Holder",
			txt=employee_name,
			filters={"company": pm_ct.COMPANY},
			page_length=20,
		)
		values = {r.get("value") for r in results if isinstance(r, dict)}
		if not values:
			values = {r[0] for r in results if isinstance(r, (list, tuple))}
		self.assertIn(holder_name, values)

	def test_get_link_title_returns_formatted_holder(self):
		emp = pm_ct._make_employee()
		holder_name = pm_ct._make_holder(emp)
		from erpnext_extensions.petty_management.overrides.search import get_link_title

		title = get_link_title("PM Holder", holder_name)
		holder_emp_name = frappe.db.get_value("PM Holder", holder_name, "employee_name")
		self.assertIn(emp, title)
		if holder_emp_name:
			self.assertIn(holder_emp_name, title)


class TestPMOpeningAdvanceLinkUX(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")
		pm_ct._ensure_company_context()
		if not pm_ct.COMPANY:
			raise unittest.SkipTest("No Company on site")
		pm_ct._ensure_petty_account()

	def _create_opening(self, holder: str, opening: float, settled: float = 0) -> str:
		doc = frappe.new_doc("PM Opening Advance")
		doc.holder = holder
		doc.opening_date = today()
		doc.opening_source_type = "Opening Balance"
		doc.opening_advance_amount = opening
		doc.previously_settled_before_migration = settled
		doc.insert(ignore_permissions=True)
		doc.submit()
		return doc.name

	def test_opening_advance_autocomplete_row_format(self):
		emp = pm_ct._make_employee()
		holder = pm_ct._make_holder(emp)
		petty = frappe.db.get_value("PM Holder", holder, "petty_cash_account")
		oa = self._create_opening(holder, 1_000, 500)
		rows = pm_opening_advance_query_for_pm_clearance(
			"PM Opening Advance",
			oa,
			"name",
			0,
			20,
			{"holder": holder, "company": pm_ct.COMPANY, "petty_cash_account": petty},
		)
		row = next(r for r in rows if r[0] == oa)
		self.assertEqual(len(row), 4)
		self.assertIn("|", row[1])
		self.assertIn("Available:", row[2])
		self.assertIn("Opening:", row[3])

	def test_format_opening_advance_link_search_row_unit(self):
		row = format_opening_advance_link_search_row(
			{
				"name": "PM-OPA-2026-06-00030",
				"employee_name": "فربد ابراهیمی",
				"employee": "HR-EMP-0496",
				"opening_advance_amount": 1000,
				"available_amount": 500,
				"currency": frappe.defaults.get_global_default("currency") or "USD",
			}
		)
		self.assertEqual(row[0], "PM-OPA-2026-06-00030")
		self.assertIn("فربد ابراهیمی", row[1])
		self.assertIn("HR-EMP-0496", row[1])
		self.assertTrue(row[2].startswith("Available:"))
		self.assertTrue(row[3].startswith("Opening:"))

	def test_standard_link_query_matches_clearance_row_shape(self):
		emp = pm_ct._make_employee()
		holder = pm_ct._make_holder(emp)
		petty = frappe.db.get_value("PM Holder", holder, "petty_cash_account")
		oa = self._create_opening(holder, 2_000, 0)
		rows = pm_opening_advance_link_query(
			"PM Opening Advance",
			oa,
			"name",
			0,
			20,
			{
				"holder": holder,
				"company": pm_ct.COMPANY,
				"petty_cash_account": petty,
				"exclude_blocked_holder": 1,
			},
		)
		self.assertTrue(rows)
		self.assertEqual(len(rows[0]), 4)
