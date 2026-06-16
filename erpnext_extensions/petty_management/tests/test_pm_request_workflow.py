# Copyright (c) 2026, Farbod Siyahpoosh and contributors
"""PM Request / PM Clearance workflow alignment with Desk actions."""

from __future__ import annotations

import unittest

import frappe
from frappe.model.workflow import WorkflowPermissionError, get_transitions

from erpnext_extensions.patches.post_model_sync.add_petty_management_workflows import (
	repair_pm_clearance_workflow,
	repair_pm_request_workflow,
)
from erpnext_extensions.petty_management.services.workflow_utils import (
	apply_pm_workflow,
	resolve_workflow_state_link,
	workflow_action_table,
)
from erpnext_extensions.petty_management.tests import test_pm_clearance as pm_ct


class TestPMRequestWorkflow(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")
		pm_ct._ensure_company_context()
		if not pm_ct.COMPANY:
			raise unittest.SkipTest("No Company on site")
		repair_pm_request_workflow()
		repair_pm_clearance_workflow()
		frappe.db.commit()

	def test_pm_request_workflow_pending_approval_state_is_canonical(self):
		wf = frappe.get_doc("Workflow", "PM Request Workflow")
		pending = [s.state for s in wf.states if "approval" in (s.state or "").lower()]
		self.assertTrue(pending)
		for st in pending:
			self.assertEqual(st, resolve_workflow_state_link("Pending Approval"))

	def test_pm_request_draft_allows_submit_for_approval_action(self):
		emp = pm_ct._make_employee()
		pm_ct._make_holder(emp)
		req = frappe.new_doc("PM Request")
		req.company = pm_ct.COMPANY
		req.employee = emp
		req.transaction_date = frappe.utils.today()
		req.append("details", {"advance_amount": 1000})
		req.insert(ignore_permissions=True)
		draft = resolve_workflow_state_link("Draft")
		frappe.db.set_value("PM Request", req.name, "workflow_state", draft, update_modified=False)
		req.reload()
		actions = [t.get("action") for t in get_transitions(req)]
		self.assertIn("PM Submit for Approval", actions)
		out = apply_pm_workflow(req, "PM Submit for Approval")
		self.assertEqual(out.docstatus, 1)
		title = frappe.db.get_value("Workflow State", out.workflow_state, "workflow_state_name")
		self.assertEqual(title, "Pending Approval")

	def test_pm_request_direct_jump_to_approved_blocked(self):
		emp = pm_ct._make_employee()
		pm_ct._make_holder(emp)
		req = frappe.new_doc("PM Request")
		req.company = pm_ct.COMPANY
		req.employee = emp
		req.transaction_date = frappe.utils.today()
		req.append("details", {"advance_amount": 500})
		req.insert(ignore_permissions=True)
		frappe.db.set_value(
			"PM Request",
			req.name,
			"workflow_state",
			resolve_workflow_state_link("Draft"),
			update_modified=False,
		)
		req.reload()
		req.workflow_state = resolve_workflow_state_link("Approved")
		with self.assertRaises(WorkflowPermissionError):
			req.save()

	def test_pm_request_workflow_action_table_matches_definition(self):
		rows = workflow_action_table("PM Request")
		self.assertTrue(rows)
		draft = next(r for r in rows if r["state"] == resolve_workflow_state_link("Draft"))
		action_names = {a["action"] for a in draft["actions"]}
		self.assertIn("PM Submit for Approval", action_names)

	def test_pm_clearance_draft_allows_finance_review_action(self):
		emp = pm_ct._make_employee()
		pm_ct._make_holder(emp)
		cl = frappe.new_doc("PM Clearance")
		cl.company = pm_ct.COMPANY
		cl.employee = emp
		cl.transaction_date = frappe.utils.today()
		cl.flags.ignore_mandatory = True
		cl.flags.ignore_validate = True
		cl.insert(ignore_permissions=True)
		draft = resolve_workflow_state_link("Draft")
		frappe.db.set_value("PM Clearance", cl.name, "workflow_state", draft, update_modified=False)
		cl.reload()
		actions = [t.get("action") for t in get_transitions(cl)]
		self.assertIn("PM Submit Finance Review", actions)

	def test_invalid_workflow_action_rejected_before_apply(self):
		emp = pm_ct._make_employee()
		pm_ct._make_holder(emp)
		req = frappe.new_doc("PM Request")
		req.company = pm_ct.COMPANY
		req.employee = emp
		req.transaction_date = frappe.utils.today()
		req.append("details", {"advance_amount": 100})
		req.insert(ignore_permissions=True)
		req.reload()
		with self.assertRaises(frappe.ValidationError):
			apply_pm_workflow(req, "PM Approve")
