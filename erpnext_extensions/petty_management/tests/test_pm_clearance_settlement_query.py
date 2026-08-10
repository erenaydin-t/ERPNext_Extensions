# Copyright (c) 2026, Farbod Siyahpoosh and contributors
"""PM Clearance settlement line PI/PO link queries."""

from __future__ import annotations

import unittest

import frappe
from frappe.utils import flt, today

from erpnext_extensions.petty_management.doctype.pm_clearance.pm_clearance import (
	purchase_invoice_query_for_pm_clearance,
	purchase_order_query_for_pm_clearance,
)
from erpnext_extensions.petty_management.tests import test_pm_clearance as tpm


class TestPMClearanceSettlementQueries(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")
		tpm._ensure_company_context()
		if not tpm.COMPANY:
			raise unittest.SkipTest("No Company on site")

	def setUp(self):
		self._created: list[tuple[str, str]] = []

	def tearDown(self):
		for dt, name in reversed(self._created):
			try:
				if frappe.db.exists(dt, name):
					doc = frappe.get_doc(dt, name)
					if doc.docstatus == 1:
						doc.cancel()
					elif doc.docstatus == 0:
						frappe.delete_doc(dt, name, force=1)
			except Exception:
				pass
		frappe.db.commit()

	def _track(self, dt: str, name: str) -> None:
		self._created.append((dt, name))

	def _submitted_pi(self, amount: float, supplier: str | None = None):
		pi = tpm._make_pi_outstanding(amount)
		if supplier:
			pi.supplier = supplier
		pi.insert(ignore_permissions=True)
		pi.submit()
		self._track("Purchase Invoice", pi.name)
		return pi

	def _submitted_po(self, supplier: str | None = None):
		po = tpm._make_purchase_order_for_company(qty=2, rate=5_000)
		if supplier:
			frappe.db.set_value("Purchase Order", po.name, "supplier", supplier, update_modified=False)
			po.reload()
		return po

	def _query_pi(self, txt: str = "", supplier: str | None = None):
		filters = {"company": tpm.COMPANY}
		if supplier:
			filters["supplier"] = supplier
		return purchase_invoice_query_for_pm_clearance("Purchase Invoice", txt, "name", 0, 50, filters)

	def _query_po(self, txt: str = "", supplier: str | None = None):
		filters = {"company": tpm.COMPANY}
		if supplier:
			filters["supplier"] = supplier
		return purchase_order_query_for_pm_clearance("Purchase Order", txt, "name", 0, 50, filters)

	def test_pi_query_finds_by_invoice_name(self):
		pi = self._submitted_pi(50_000)
		rows = self._query_pi(pi.name)
		names = {r[0] for r in rows}
		self.assertIn(pi.name, names)
		self.assertIn("|", rows[0][1])

	def test_pi_query_finds_by_supplier_code(self):
		pi = self._submitted_pi(40_000)
		rows = self._query_pi(pi.supplier[:6])
		self.assertTrue(any(r[0] == pi.name for r in rows))

	def test_pi_query_finds_by_supplier_name(self):
		supplier = None
		for s in frappe.get_all("Supplier", fields=["name", "supplier_name"], limit=20):
			if s.supplier_name and s.supplier_name != s.name:
				supplier = s.name
				break
		if not supplier:
			supplier = frappe.get_all("Supplier", pluck="name", limit=1)[0]
			unique = f"PM Search Supplier {frappe.generate_hash(length=6)}"
			frappe.db.set_value("Supplier", supplier, "supplier_name", unique)
			search_txt = unique[3:12]
		else:
			search_txt = (frappe.db.get_value("Supplier", supplier, "supplier_name") or "")[:8]
		pi = self._submitted_pi(35_000, supplier=supplier)
		rows = self._query_pi(search_txt)
		self.assertTrue(any(r[0] == pi.name for r in rows))
		desc = next(r[1] for r in rows if r[0] == pi.name)
		self.assertIn(supplier, desc)
		self.assertIn("Outstanding:", desc)

	def test_pi_query_includes_draft(self):
		"""v4.1.5: Draft PI appears in lookup with Draft status / Grand Total."""
		pi = tpm._make_pi_outstanding(1_000)
		pi.insert(ignore_permissions=True)
		self._track("Purchase Invoice", pi.name)
		rows = self._query_pi(pi.name)
		self.assertIn(pi.name, {r[0] for r in rows})
		desc = next(r[1] for r in rows if r[0] == pi.name)
		self.assertIn("Draft", desc)
		self.assertIn("Grand Total", desc)

	def test_pi_query_excludes_cancelled(self):
		pi = self._submitted_pi(2_000)
		pi.cancel()
		rows = self._query_pi(pi.name)
		self.assertNotIn(pi.name, {r[0] for r in rows})

	def test_pi_query_excludes_zero_outstanding(self):
		pi = self._submitted_pi(100)
		frappe.db.set_value("Purchase Invoice", pi.name, "outstanding_amount", 0, update_modified=False)
		rows = self._query_pi(pi.name)
		self.assertNotIn(pi.name, {r[0] for r in rows})

	def test_po_query_finds_by_name_and_supplier(self):
		po = self._submitted_po()
		self._track("Purchase Order", po.name)
		rows = self._query_po(po.name)
		self.assertTrue(any(r[0] == po.name for r in rows))
		rows2 = self._query_po(po.supplier[:5])
		self.assertTrue(any(r[0] == po.name for r in rows2))

	def test_po_query_excludes_draft(self):
		po = tpm._make_purchase_order_for_company()
		frappe.db.set_value("Purchase Order", po.name, "docstatus", 0, update_modified=False)
		self._track("Purchase Order", po.name)
		rows = self._query_po(po.name)
		self.assertNotIn(po.name, {r[0] for r in rows})

	def test_po_query_excludes_cancelled(self):
		po = self._submitted_po()
		self._track("Purchase Order", po.name)
		doc = frappe.get_doc("Purchase Order", po.name)
		doc.cancel()
		rows = self._query_po(po.name)
		self.assertNotIn(po.name, {r[0] for r in rows})

	def test_integration_clearance_save_after_pi_from_query(self):
		from erpnext_extensions.petty_management.tests.test_pm_clearance import (
			_append_pm_clearance_detail_row,
		)

		emp = tpm._make_employee()
		self._track("Employee", emp)
		tpm._make_holder(emp)
		req_name, _pe = tpm._fund_pm_request(emp, 100_000.0)
		self._track("PM Request", req_name)
		pi = self._submitted_pi(5_000)
		rows = self._query_pi(pi.supplier)
		self.assertTrue(any(r[0] == pi.name for r in rows))
		cl = frappe.new_doc("PM Clearance")
		cl.company = tpm.COMPANY
		cl.employee = emp
		cl.transaction_date = today()
		_append_pm_clearance_detail_row(
			cl,
			{
				"settlement_type": "Purchase Invoice",
				"purchase_invoice": pi.name,
				"allocated_amount": 5_000,
			},
		)
		cl.append("request_allocations", {"pm_request": req_name, "allocated_amount": 5_000})
		cl.insert(ignore_permissions=True)
		self._track("PM Clearance", cl.name)
		line = cl.details[0]
		self.assertEqual(line.purchase_invoice, pi.name)
		self.assertEqual(line.supplier, pi.supplier)
		self.assertEqual(flt(line.outstanding_amount), flt(pi.outstanding_amount))
