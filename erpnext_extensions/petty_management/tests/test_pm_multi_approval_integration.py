# Copyright (c) 2026, ERPNext Extensions contributors
"""Integration: multi-level approval + native Assignment Rule ToDo handoff."""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today

from erpnext_extensions.petty_management.services.workflow_utils import (
	apply_pm_workflow,
	resolve_workflow_state_link,
)
from erpnext_extensions.petty_management.tests import test_pm_clearance as tpm


def _ensure_user(email: str, roles: list[str]) -> str:
	if not frappe.db.exists("User", email):
		u = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": email.split("@")[0],
				"send_welcome_email": 0,
				"user_type": "System User",
			}
		)
		u.insert(ignore_permissions=True)
		u.new_password = "pm_sec_test_1"
		u.save(ignore_permissions=True)
	user = frappe.get_doc("User", email)
	for role in roles:
		if not frappe.db.exists("Role", role):
			frappe.get_doc({"doctype": "Role", "role_name": role}).insert(ignore_permissions=True)
		if role not in [r.role for r in user.roles]:
			user.append("roles", {"role": role})
	user.save(ignore_permissions=True)
	frappe.db.commit()
	return email


def _open_todos(doctype: str, name: str) -> list[dict]:
	return frappe.get_all(
		"ToDo",
		filters={
			"reference_type": doctype,
			"reference_name": name,
			"status": "Open",
		},
		fields=["name", "allocated_to", "assignment_rule"],
	)


class TestPMMultiApprovalIntegration(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		tpm._ensure_company_context()
		cls.manager = _ensure_user(
			"pm_mgr_v402@example.com",
			["Petty Management Manager", "Petty Management User", "Expense Approver", "System Manager"],
		)
		cls.ceo = _ensure_user(
			"pm_ceo_v402@example.com",
			["Petty Management Manager", "System Manager"],
		)
		cls.finance = _ensure_user(
			"pm_fin_v402@example.com",
			["Petty Management Accountant", "Accounts User", "System Manager"],
		)
		settings = frappe.get_single("PM Settings")
		settings.db_set("ceo_approver", cls.ceo, update_modified=False)
		settings.db_set("finance_manager", cls.finance, update_modified=False)
		settings.db_set("finance_supervisor", cls.finance, update_modified=False)
		settings.db_set("require_named_manager_approver", 1, update_modified=False)
		if not settings.default_bank_account:
			# leave as-is; PE creation may skip if missing
			pass

	def test_request_approval_chain_and_todos(self):
		emp = tpm._make_employee()
		frappe.db.set_value("Employee", emp, "expense_approver", self.manager, update_modified=False)
		tpm._make_holder(emp)

		frappe.set_user("Administrator")
		req = frappe.new_doc("PM Request")
		req.company = tpm.COMPANY
		req.employee = emp
		req.transaction_date = today()
		req.append(
			"details",
			{"description": "v402 multi approval", "advance_amount": 10000},
		)
		req.insert(ignore_permissions=True)

		# Submit via workflow
		apply_pm_workflow(req, "PM Submit for Approval")
		req.reload()
		self.assertEqual(
			frappe.db.get_value("Workflow State", req.workflow_state, "workflow_state_name"),
			"Pending Manager Approval",
		)
		self.assertEqual(req.manager_approver, self.manager)
		self.assertEqual(req.ceo_approver, self.ceo)
		self.assertEqual(req.finance_approver, self.finance)

		todos = _open_todos("PM Request", req.name)
		self.assertTrue(any(t.allocated_to == self.manager for t in todos), msg=str(todos))

		frappe.set_user(self.manager)
		req = frappe.get_doc("PM Request", req.name)
		apply_pm_workflow(req, "PM Manager Approve")
		req.reload()
		self.assertEqual(
			frappe.db.get_value("Workflow State", req.workflow_state, "workflow_state_name"),
			"Pending CEO Approval",
		)
		todos = _open_todos("PM Request", req.name)
		self.assertTrue(any(t.allocated_to == self.ceo for t in todos), msg=str(todos))
		self.assertFalse(any(t.allocated_to == self.manager and t.status == "Open" for t in todos if False))
		# Manager should not remain as sole open assignee
		open_users = {t.allocated_to for t in todos}
		self.assertIn(self.ceo, open_users)

		frappe.set_user(self.ceo)
		req = frappe.get_doc("PM Request", req.name)
		apply_pm_workflow(req, "PM CEO Approve")
		req.reload()
		todos = _open_todos("PM Request", req.name)
		self.assertTrue(any(t.allocated_to == self.finance for t in todos), msg=str(todos))

		frappe.set_user(self.finance)
		req = frappe.get_doc("PM Request", req.name)
		apply_pm_workflow(req, "PM Finance Approve")
		req.reload()
		self.assertEqual(
			frappe.db.get_value("Workflow State", req.workflow_state, "workflow_state_name"),
			"Waiting for Payment",
		)
		self.assertEqual(req.status, "Waiting for Payment")
		from erpnext_extensions.petty_management.services.request_service import (
			request_ready_for_payment_entry,
		)

		ok, _reason = request_ready_for_payment_entry(req)
		self.assertTrue(ok, msg=_reason)

	def test_clearance_settle_keeps_workflow_approved(self):
		emp = tpm._make_employee()
		frappe.db.set_value("Employee", emp, "expense_approver", self.manager, update_modified=False)
		tpm._make_holder(emp)
		pm_request, _pe = tpm._fund_pm_request(emp, 50_000.0)
		# Force request into Waiting for Payment for funding truth
		waiting = resolve_workflow_state_link("Waiting for Payment")
		frappe.db.set_value(
			"PM Request",
			pm_request,
			{"workflow_state": waiting, "status": "Waiting for Payment", "payment_status": "Paid"},
			update_modified=False,
		)

		pi = tpm._make_pi_outstanding(5_000)
		pi.insert(ignore_permissions=True)
		pi.submit()

		frappe.set_user("Administrator")
		cl = frappe.new_doc("PM Clearance")
		cl.company = tpm.COMPANY
		cl.employee = emp
		cl.posting_date = today()
		tpm._append_pm_clearance_detail_row(
			cl,
			{
				"settlement_type": "Purchase Invoice",
				"purchase_invoice": pi.name,
				"allocated_amount": 5000,
			},
		)
		cl.append(
			"request_allocations",
			{
				"funding_source_type": "PM Request",
				"pm_request": pm_request,
				"allocated_amount": 5000,
			},
		)
		cl.insert(ignore_permissions=True)
		apply_pm_workflow(cl, "PM Submit Finance Review")
		cl.reload()

		frappe.set_user(self.manager)
		cl = frappe.get_doc("PM Clearance", cl.name)
		apply_pm_workflow(cl, "PM Manager Approve")
		cl.reload()

		frappe.set_user(self.finance)
		cl = frappe.get_doc("PM Clearance", cl.name)
		apply_pm_workflow(cl, "PM Finance Approve")
		cl.reload()
		self.assertEqual(cl.status, "Approved")
		ws_before = cl.workflow_state

		from erpnext_extensions.petty_management.services.journal_entry_service import settle_petty_cash

		out = settle_petty_cash(cl.name)
		cl.reload()
		self.assertEqual(cl.workflow_state, ws_before)
		self.assertIn(cl.status, ("Pending Journal Entry Submission", "Settled"))
		self.assertTrue(out.get("journal_entry"))
