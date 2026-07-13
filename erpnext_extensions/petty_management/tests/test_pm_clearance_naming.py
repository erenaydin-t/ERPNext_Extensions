# Copyright (c) 2026, Farbod Siyahpoosh and contributors
"""PM Clearance autoname — uniqueness and tabSeries contention."""

from __future__ import annotations

import unittest
from concurrent.futures import ThreadPoolExecutor, as_completed

import frappe
from frappe.exceptions import QueryDeadlockError, QueryTimeoutError
from frappe.utils import today

import erpnext_extensions.petty_management.tests.test_pm_clearance as pm_ct
from erpnext_extensions.petty_management.services.clearance_naming import assign_pm_clearance_name


class TestPMClearanceNaming(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")
		pm_ct._ensure_company_context()
		if not pm_ct.COMPANY:
			raise unittest.SkipTest("No Company on site")

	def _shell(self, employee: str):
		doc = frappe.new_doc("PM Clearance")
		doc.employee = employee
		doc.company = pm_ct.COMPANY
		doc.transaction_date = today()
		return doc

	def test_sequential_autoname_same_employee_all_unique(self):
		emp = pm_ct._make_employee()
		names: list[str] = []
		for _ in range(10):
			doc = self._shell(emp)
			assign_pm_clearance_name(doc)
			names.append(doc.name)
		self.assertEqual(len(names), len(set(names)))
		for name in names:
			self.assertTrue(name.startswith("CLR-"))
			self.assertIn(emp, name)
			# Hash suffix — no tabSeries sequential digits required
			self.assertRegex(name, rf"^CLR-{emp}-\d{{6}}-[a-zA-Z0-9]{{12}}$")

	def test_concurrent_autoname_same_employee_no_timeout(self):
		emp = pm_ct._make_employee()
		frappe.db.commit()
		site = frappe.local.site
		company = pm_ct.COMPANY

		def worker(_idx: int) -> str:
			frappe.init(site=site)
			frappe.connect()
			frappe.set_user("Administrator")
			try:
				doc = frappe.new_doc("PM Clearance")
				doc.employee = emp
				doc.company = company
				doc.transaction_date = today()
				assign_pm_clearance_name(doc)
				frappe.db.commit()
				return doc.name
			finally:
				frappe.destroy()

		names: list[str] = []
		errors: list[BaseException] = []
		with ThreadPoolExecutor(max_workers=6) as pool:
			futures = [pool.submit(worker, i) for i in range(6)]
			for fut in as_completed(futures):
				try:
					names.append(fut.result())
				except (QueryTimeoutError, QueryDeadlockError) as exc:
					errors.append(exc)
				except Exception as exc:
					errors.append(exc)

		self.assertFalse(errors, errors)
		self.assertEqual(len(names), 6)
		self.assertEqual(len(names), len(set(names)))

	def test_concurrent_pm_clearance_insert_gets_unique_names(self):
		emp = pm_ct._make_employee()
		frappe.db.commit()
		site = frappe.local.site
		company = pm_ct.COMPANY

		def worker(_idx: int) -> str:
			frappe.init(site=site)
			frappe.connect()
			frappe.set_user("Administrator")
			try:
				doc = frappe.new_doc("PM Clearance")
				doc.employee = emp
				doc.company = company
				doc.transaction_date = today()
				doc.flags.ignore_mandatory = True
				doc.flags.ignore_validate = True
				doc.insert(ignore_permissions=True, ignore_links=True)
				frappe.db.commit()
				return doc.name
			finally:
				frappe.destroy()

		names: list[str] = []
		errors: list[BaseException] = []
		with ThreadPoolExecutor(max_workers=8) as pool:
			futures = [pool.submit(worker, i) for i in range(8)]
			for fut in as_completed(futures):
				try:
					names.append(fut.result())
				except (QueryTimeoutError, QueryDeadlockError) as exc:
					errors.append(exc)
				except Exception as exc:
					errors.append(exc)

		self.assertFalse(errors, errors)
		self.assertEqual(len(names), 8)
		self.assertEqual(len(names), len(set(names)))
