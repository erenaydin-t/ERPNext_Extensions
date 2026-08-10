# Copyright (c) 2026, ERPNext Extensions contributors
"""v4.0.2: business status sync; PE/JE must never write workflow_state."""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from erpnext_extensions.petty_management.services.business_status_service import (
	CLR_APPROVED,
	CLR_PENDING_JE,
	CLR_SETTLED,
	REQ_CLOSED,
	REQ_PAID,
	REQ_PENDING_APPROVAL,
	REQ_WAITING_FOR_PAYMENT,
	sync_pm_clearance_business_status,
	sync_pm_request_business_status,
)
from erpnext_extensions.petty_management.services.workflow_utils import resolve_workflow_state_link


class TestPMBusinessStatus(FrappeTestCase):
	def test_request_pending_and_waiting(self):
		doc = frappe._dict(
			docstatus=1,
			workflow_state=resolve_workflow_state_link("Pending Manager Approval"),
			payment_status="Not Paid",
			is_closed=0,
			status="",
		)
		self.assertEqual(sync_pm_request_business_status(doc), "Pending Manager Approval")

		doc.workflow_state = resolve_workflow_state_link("Finance Approved")
		self.assertEqual(sync_pm_request_business_status(doc), REQ_WAITING_FOR_PAYMENT)

	def test_request_paid_and_closed_priority(self):
		doc = frappe._dict(
			docstatus=1,
			workflow_state=resolve_workflow_state_link("Finance Approved"),
			payment_status="Paid",
			is_closed=0,
			status="",
		)
		self.assertEqual(sync_pm_request_business_status(doc), REQ_PAID)

		doc.payment_status = "Partially Paid"
		doc.is_closed = 1
		self.assertEqual(sync_pm_request_business_status(doc), REQ_CLOSED)

	def test_clearance_je_sets_status_not_workflow(self):
		approved = resolve_workflow_state_link("Approved")
		doc = frappe._dict(
			doctype="PM Clearance",
			name="CLR-TEST-STATUS",
			docstatus=1,
			workflow_state=approved,
			status="Approved",
			journal_entry=None,
		)
		ws_before = doc.workflow_state
		self.assertEqual(sync_pm_clearance_business_status(doc), CLR_APPROVED)
		self.assertEqual(doc.workflow_state, ws_before)

	def test_je_submit_hook_does_not_change_workflow_state(self):
		"""Invariant: sync_pm_clearance_business_status never writes workflow_state."""
		approved = resolve_workflow_state_link("Approved")
		doc = frappe._dict(
			doctype="PM Clearance",
			name="CLR-TEST-INVARIANT",
			docstatus=1,
			workflow_state=approved,
			status="Approved",
			journal_entry=None,
		)
		ws_before = doc.workflow_state
		sync_pm_clearance_business_status(doc, persist=False)
		self.assertEqual(doc.workflow_state, ws_before)
		self.assertEqual(doc.status, CLR_APPROVED)

		# Pretend submitted JE exists by patching helper
		import erpnext_extensions.petty_management.services.business_status_service as bss

		orig = bss._journal_entry_docstatus
		try:
			bss._journal_entry_docstatus = lambda _je: 1
			doc.journal_entry = "ACC-JV-FAKE"
			sync_pm_clearance_business_status(doc, persist=False)
			self.assertEqual(doc.status, CLR_SETTLED)
			self.assertEqual(doc.workflow_state, ws_before)
			bss._journal_entry_docstatus = lambda _je: 0
			sync_pm_clearance_business_status(doc, persist=False)
			self.assertEqual(doc.status, CLR_PENDING_JE)
			self.assertEqual(doc.workflow_state, ws_before)
		finally:
			bss._journal_entry_docstatus = orig

	def test_stamp_service_does_not_create_todo_api(self):
		import inspect
		import re

		from erpnext_extensions.petty_management.services import approver_stamp_service as mod

		src = inspect.getsource(mod)
		# Ban real ToDo/assignment API usage — ignore docstring mentions.
		body = re.sub(r'""".*?"""', "", src, flags=re.S)
		body = re.sub(r"'''.*?'''", "", body, flags=re.S)
		self.assertNotIn('get_doc("ToDo")', body)
		self.assertNotIn("assign_to.add", body)
		self.assertNotIn("assign_to.clear", body)
		self.assertNotIn("from frappe.desk.form", body)
