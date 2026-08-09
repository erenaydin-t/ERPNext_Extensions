# Copyright (c) 2026, ERPNext Extensions contributors

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from erpnext_extensions.petty_management.services.workflow_utils import resolve_workflow_state_link


class TestPMAssignmentRules(FrappeTestCase):
	def test_assignment_rules_seeded(self):
		expected = [
			"PM Request Manager Approval",
			"PM Request CEO Approval",
			"PM Request Finance Approval",
			"PM Clearance Manager Approval",
			"PM Clearance Finance Review",
		]
		# Ensure seed ran
		from erpnext_extensions.patches.post_model_sync.migrate_pm_workflow_v402 import (
			_seed_assignment_rules,
		)

		_seed_assignment_rules()
		for name in expected:
			self.assertTrue(frappe.db.exists("Assignment Rule", name), msg=name)
			rule = frappe.get_doc("Assignment Rule", name)
			self.assertEqual(rule.rule, "Based on Field")
			self.assertFalse(cint(rule.disabled))
			self.assertTrue(rule.field)
			self.assertTrue(rule.assign_condition)
			self.assertTrue(rule.unassign_condition)

	def test_workflow_states_v402(self):
		req_states = {
			resolve_workflow_state_link(t)
			for t in (
				"Draft",
				"Pending Manager Approval",
				"Pending CEO Approval",
				"Pending Finance Approval",
				"Waiting for Payment",
				"Rejected",
			)
		}
		wf = frappe.get_doc("Workflow", "PM Request Workflow")
		have = {row.state for row in wf.states}
		self.assertTrue(req_states.issubset(have) or all(resolve_workflow_state_link(s) in have for s in req_states))
		# Clearance must not list Settled as workflow state
		cwf = frappe.get_doc("Workflow", "PM Clearance Workflow")
		titles = {
			frappe.db.get_value("Workflow State", row.state, "workflow_state_name") or row.state
			for row in cwf.states
		}
		self.assertNotIn("Settled", titles)
		self.assertNotIn("Pending Journal Entry Submission", titles)


def cint(v):
	from frappe.utils import cint as _c

	return _c(v)
