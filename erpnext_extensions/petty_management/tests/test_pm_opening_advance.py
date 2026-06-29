# Copyright (c) 2026, Farbod Siyahpoosh and contributors
"""PM Opening Advance — ledger balances, clearance allocation, cancel restore."""

from __future__ import annotations

import unittest

import frappe
from frappe.exceptions import ValidationError
from frappe.utils import flt, today

from erpnext_extensions.petty_management.services.opening_advance_service import (
	get_opening_advance_available_amount,
	pm_opening_advance_query_for_pm_clearance,
	remaining_at_cutover_amount,
	sum_prior_opening_allocations,
)
import erpnext_extensions.petty_management.tests.test_pm_clearance as pm_ct


def _submit_pi_or_skip(pi):
	try:
		pi.insert(ignore_permissions=True)
		pi.submit()
	except TypeError as exc:
		if "do_not_round_fields" in str(exc):
			raise unittest.SkipTest("Purchase Invoice submit incompatible with this Frappe version") from exc
		raise


class TestPMOpeningAdvance(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")
		pm_ct._ensure_company_context()
		if not pm_ct.COMPANY:
			raise unittest.SkipTest("No Company on site")
		pm_ct._ensure_petty_account()

	def setUp(self):
		frappe.set_user("Administrator")

	def _create_opening(
		self,
		holder: str,
		suffix: str,
		opening: float,
		previously_settled: float = 0,
	) -> str:
		doc = frappe.new_doc("PM Opening Advance")
		doc.holder = holder
		doc.opening_date = today()
		doc.opening_source_type = "Legacy Advance"
		doc.opening_advance_amount = opening
		doc.previously_settled_before_migration = previously_settled
		doc.reference_no = suffix
		doc.insert(ignore_permissions=True)
		doc.submit()
		return doc.name

	def test_remaining_at_cutover_formula(self):
		self.assertEqual(remaining_at_cutover_amount(100_000, 40_000), 60_000)

	def test_previously_settled_cannot_exceed_opening(self):
		emp = pm_ct._make_employee()
		holder = pm_ct._make_holder(emp)
		doc = frappe.new_doc("PM Opening Advance")
		doc.holder = holder
		doc.opening_date = today()
		doc.opening_source_type = "Opening Balance"
		doc.opening_advance_amount = 10_000
		doc.previously_settled_before_migration = 20_000
		with self.assertRaises(ValidationError):
			doc.insert()

	def test_multiple_submitted_openings_same_holder(self):
		emp = pm_ct._make_employee()
		holder = pm_ct._make_holder(emp)
		a = self._create_opening(holder, "A", 30_000, 0)
		b = self._create_opening(holder, "B", 20_000, 5_000)
		self.assertNotEqual(a, b)
		self.assertEqual(get_opening_advance_available_amount(a), 30_000)
		self.assertEqual(get_opening_advance_available_amount(b), 15_000)

	def test_lookup_includes_zero_available_opening(self):
		emp = pm_ct._make_employee()
		holder = pm_ct._make_holder(emp)
		petty = frappe.db.get_value("PM Holder", holder, "petty_cash_account")
		company = pm_ct.COMPANY
		oa = self._create_opening(holder, "LOOKUP-ZERO", 10_000, 10_000)
		self.assertEqual(get_opening_advance_available_amount(oa), 0)
		rows = pm_opening_advance_query_for_pm_clearance(
			"PM Opening Advance",
			"",
			"name",
			0,
			50,
			{"holder": holder, "company": company, "petty_cash_account": petty},
		)
		names = {r[0] for r in rows}
		self.assertIn(oa, names)
		match = next(r for r in rows if r[0] == oa)
		self.assertEqual(len(match), 4)
		self.assertIn("Available:", match[2])
		self.assertIn("0", match[2].replace(",", ""))

	def test_lookup_shows_opening_and_available_columns(self):
		emp = pm_ct._make_employee()
		holder = pm_ct._make_holder(emp)
		petty = frappe.db.get_value("PM Holder", holder, "petty_cash_account")
		oa = self._create_opening(holder, "LOOKUP-COLS", 50_000, 10_000)
		rows = pm_opening_advance_query_for_pm_clearance(
			"PM Opening Advance",
			oa,
			"name",
			0,
			50,
			{
				"holder": holder,
				"company": pm_ct.COMPANY,
				"petty_cash_account": petty,
			},
		)
		self.assertTrue(rows)
		row = rows[0]
		self.assertEqual(row[0], oa)
		self.assertIn("|", row[1])
		self.assertIn("Available:", row[2])
		self.assertIn("Opening:", row[3])
		self.assertEqual(get_opening_advance_available_amount(oa), 40_000)

	def test_over_allocation_fails_on_save(self):
		emp = pm_ct._make_employee()
		holder = pm_ct._make_holder(emp)
		oa = self._create_opening(holder, "OVER", 10_000, 0)
		over_amount = 10_001
		pi = pm_ct._make_pi_outstanding(over_amount)
		_submit_pi_or_skip(pi)
		cl = frappe.new_doc("PM Clearance")
		cl.company = pm_ct.COMPANY
		cl.employee = emp
		cl.transaction_date = today()
		pm_ct._append_pm_clearance_detail_row(
			cl,
			{
				"settlement_type": "Purchase Invoice",
				"purchase_invoice": pi.name,
				"allocated_amount": over_amount,
			},
		)
		cl.append(
			"request_allocations",
			{
				"funding_source_type": "PM Opening Advance",
				"pm_opening_advance": oa,
				"allocated_amount": over_amount,
			},
		)
		with self.assertRaises(ValidationError):
			cl.insert(ignore_permissions=True)

	def test_opening_allocation_and_cancel_restore(self):
		emp = pm_ct._make_employee()
		holder = pm_ct._make_holder(emp)
		oa = self._create_opening(holder, "E2E", 100_000, 40_000)
		self.assertEqual(get_opening_advance_available_amount(oa), 60_000)

		pi = pm_ct._make_pi_outstanding(25_000)
		_submit_pi_or_skip(pi)
		cl = frappe.new_doc("PM Clearance")
		cl.company = pm_ct.COMPANY
		cl.employee = emp
		cl.transaction_date = today()
		pm_ct._append_pm_clearance_detail_row(
			cl,
			{
				"settlement_type": "Purchase Invoice",
				"purchase_invoice": pi.name,
				"allocated_amount": 20_000,
			},
		)
		cl.append(
			"request_allocations",
			{
				"funding_source_type": "PM Opening Advance",
				"pm_opening_advance": oa,
				"allocated_amount": 20_000,
			},
		)
		cl.insert(ignore_permissions=True)
		cl.submit()
		pm_ct._approve_pm_clearance_for_reservation(cl.name)
		self.assertEqual(get_opening_advance_available_amount(oa), 40_000)
		self.assertEqual(sum_prior_opening_allocations(oa), 20_000)

		cl2 = frappe.copy_doc(cl)
		cl2.name = None
		cl2.docstatus = 0
		cl2.workflow_state = None
		cl2.status = "Draft"
		cl2.details = []
		cl2.request_allocations = []
		pm_ct._append_pm_clearance_detail_row(
			cl2,
			{
				"settlement_type": "Purchase Invoice",
				"purchase_invoice": pi.name,
				"allocated_amount": 15_000,
			},
		)
		cl2.append(
			"request_allocations",
			{
				"funding_source_type": "PM Opening Advance",
				"pm_opening_advance": oa,
				"allocated_amount": 15_000,
			},
		)
		cl2.insert(ignore_permissions=True)
		cl2.submit()
		pm_ct._approve_pm_clearance_for_reservation(cl2.name)
		self.assertEqual(get_opening_advance_available_amount(oa), 25_000)

		cl2.cancel()
		frappe.db.set_value("PM Clearance", cl2.name, "status", "Cancelled", update_modified=False)
		self.assertEqual(get_opening_advance_available_amount(oa), 40_000)

	def test_pm_request_still_requires_pe(self):
		emp = pm_ct._make_employee()
		pm_ct._make_holder(emp)
		req_name, _pe = pm_ct._fund_pm_request(emp, 5_000)
		pi = pm_ct._make_pi_outstanding(5_000)
		_submit_pi_or_skip(pi)
		cl = frappe.new_doc("PM Clearance")
		cl.company = pm_ct.COMPANY
		cl.employee = emp
		cl.transaction_date = today()
		pm_ct._append_pm_clearance_detail_row(
			cl,
			{"settlement_type": "Purchase Invoice", "purchase_invoice": pi.name, "allocated_amount": 1_000},
		)
		cl.append(
			"request_allocations",
			{"funding_source_type": "PM Request", "pm_request": req_name, "allocated_amount": 1_000},
		)
		cl.insert(ignore_permissions=True)
		self.assertTrue(cl.request_allocations[0].paid_amount > 0)

	def test_no_payment_entry_for_opening_advance_name(self):
		emp = pm_ct._make_employee()
		holder = pm_ct._make_holder(emp)
		oa = self._create_opening(holder, "PE-CHECK", 10_000)
		count = frappe.db.count("Payment Entry", {"reference_no": oa, "docstatus": ["<", 2]})
		self.assertEqual(count, 0)

	def test_opening_availability_report_without_migration_batch(self):
		from erpnext_extensions.petty_management.services.report_service import (
			get_pm_opening_advance_availability_report_data,
		)

		columns, data = get_pm_opening_advance_availability_report_data({"company": pm_ct.COMPANY})
		fieldnames = {c["fieldname"] for c in columns}
		self.assertNotIn("migration_batch", fieldnames)
		self.assertIn("reference_no", fieldnames)
		self.assertIsInstance(data, list)

	def test_pm_balance_report_shows_split_balances(self):
		from erpnext_extensions.petty_management.services.report_service import get_pm_balance_report_data

		columns, _data = get_pm_balance_report_data({})
		labels = [c["label"] for c in columns]
		fieldnames = [c["fieldname"] for c in columns]
		for label in ("Funded Balance", "Opening Balance", "Total Available"):
			self.assertIn(label, labels)
		idx_funded = fieldnames.index("funded_available_amount")
		idx_opening = fieldnames.index("opening_available_amount")
		idx_total = fieldnames.index("current_balance")
		self.assertLess(idx_funded, idx_total)
		self.assertLess(idx_opening, idx_total)
