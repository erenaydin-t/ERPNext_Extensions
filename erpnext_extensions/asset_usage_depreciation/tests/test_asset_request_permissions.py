# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

"""Permission matrix for Asset Request (employee vs fulfillment roles)."""

from __future__ import annotations

import unittest

import frappe
from frappe.utils import random_string

from erpnext_extensions.asset_usage_depreciation.constants import (
	ROLE_AR_EXECUTIVE,
	ROLE_AR_MANAGER,
	ROLE_AR_PLANNER,
	ROLE_ASSET_MANAGER,
)
from erpnext_extensions.asset_usage_depreciation.permissions import (
	asset_request_permission_query_conditions,
	has_asset_request_permission,
)
from erpnext_extensions.asset_usage_depreciation.tests import test_helpers as h


class TestAssetRequestPermissions(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")
		cls.skip = h.skip_if_unready()
		if cls.skip:
			return
		h.ensure_settings(
			prevent_duplicate_active_requests=0,
			require_named_manager_approver=0,
		)
		cls.company = h.company()
		suffix = random_string(6).lower()
		cls.emp_user = h.make_user(
			email=f"ar.emp.{suffix}@example.com",
			roles=["Employee"],
		)
		cls.mgr_user = h.make_user(
			email=f"ar.mgr.{suffix}@example.com",
			roles=["Employee", ROLE_AR_MANAGER],
		)
		cls.planner_user = h.make_user(
			email=f"ar.pln.{suffix}@example.com",
			roles=["Employee", ROLE_AR_PLANNER],
		)
		cls.ceo_user = h.make_user(
			email=f"ar.ceo.{suffix}@example.com",
			roles=["Employee", ROLE_AR_EXECUTIVE],
		)
		cls.am_user = h.make_user(
			email=f"ar.am.{suffix}@example.com",
			roles=["Employee", ROLE_ASSET_MANAGER],
		)
		cls.other_user = h.make_user(
			email=f"ar.oth.{suffix}@example.com",
			roles=["Employee"],
		)
		cls.employee = h.make_employee(company_name=cls.company, user_id=cls.emp_user)
		cls.other_employee = h.make_employee(company_name=cls.company, user_id=cls.other_user)
		cls.item = h.make_fixed_asset_item(title="Perm Item")

	def _ready(self):
		if getattr(self, "skip", None):
			self.skipTest(self.skip)

	def test_employee_sees_own_request_only(self):
		self._ready()
		own = h.make_request(company_name=self.company, employee=self.employee, item_code=self.item)
		other = h.make_request(company_name=self.company, employee=self.other_employee, item_code=self.item)
		self.assertTrue(has_asset_request_permission(own, user=self.emp_user))
		self.assertFalse(has_asset_request_permission(other, user=self.emp_user))
		self.assertTrue(has_asset_request_permission(own, user=self.am_user))
		self.assertTrue(has_asset_request_permission(other, user=self.am_user))
		sql = asset_request_permission_query_conditions(self.emp_user)
		self.assertIn("employee", sql)
		self.assertEqual(asset_request_permission_query_conditions(self.am_user), "")

	def test_approver_roles_are_unrestricted_or_stamped(self):
		self._ready()
		doc = h.make_request(company_name=self.company, employee=self.employee, item_code=self.item)
		doc.manager_approver = self.mgr_user
		doc.planning_approver = self.planner_user
		doc.ceo_approver = self.ceo_user
		self.assertTrue(has_asset_request_permission(doc, user=self.mgr_user))
		self.assertTrue(has_asset_request_permission(doc, user=self.planner_user))
		self.assertTrue(has_asset_request_permission(doc, user=self.ceo_user))
		# Planner / Executive are unrestricted list visibility (optional stages).
		self.assertEqual(asset_request_permission_query_conditions(self.planner_user), "")
		self.assertEqual(asset_request_permission_query_conditions(self.ceo_user), "")

	def test_employee_cannot_write_fulfillment_permlevel(self):
		self._ready()
		meta = frappe.get_meta("Asset Request")
		emp_pl1 = [
			p
			for p in meta.permissions
			if p.role == "Employee" and int(p.permlevel or 0) == 1 and int(p.write or 0)
		]
		self.assertFalse(emp_pl1, "Employee must not have permlevel 1 write")
		item_meta = frappe.get_meta("Asset Request Item")
		self.assertEqual(item_meta.get_field("fulfilled_item_code").permlevel, 1)
		self.assertEqual(meta.get_field("allocations").permlevel, 1)
		am_pl1 = [
			p
			for p in meta.permissions
			if p.role == ROLE_ASSET_MANAGER and int(p.permlevel or 0) == 1 and int(p.write or 0)
		]
		self.assertTrue(am_pl1)

	def test_employee_cannot_edit_allocation_or_fulfilled_after_approval(self):
		self._ready()
		doc = h.make_request(company_name=self.company, employee=self.employee, item_code=self.item)
		frappe.set_user(self.emp_user)
		try:
			as_emp = frappe.get_doc("Asset Request", doc.name)
			as_emp.append(
				"allocations",
				{
					"requested_item_code": self.item,
					"fulfilled_item_code": self.item,
					"method": "Issue Existing",
					"qty": 1,
				},
			)
			try:
				as_emp.save()
			except (frappe.PermissionError, frappe.ValidationError, frappe.exceptions.ValidationError):
				pass
		finally:
			frappe.set_user("Administrator")
		doc.reload()
		self.assertFalse(doc.allocations, "Employee must not persist allocation rows")

		h.submit_and_approve(doc)
		before_fulfilled = doc.items[0].fulfilled_item_code
		frappe.set_user(self.emp_user)
		try:
			submitted = frappe.get_doc("Asset Request", doc.name)
			submitted.items[0].fulfilled_item_code = self.item
			submitted.items[0].substitution_reason = "should not stick"
			with self.assertRaises((frappe.UpdateAfterSubmitError, frappe.PermissionError, frappe.ValidationError)):
				submitted.save()
		finally:
			frappe.set_user("Administrator")
		doc.reload()
		self.assertEqual(doc.items[0].fulfilled_item_code, before_fulfilled)

	def test_manager_can_approve_and_reject(self):
		self._ready()
		from frappe.model.workflow import apply_workflow

		approve_doc = h.make_request(company_name=self.company, employee=self.employee, item_code=self.item)
		approve_doc.manager_approver = self.mgr_user
		approve_doc.require_planning_approval = 0
		approve_doc.require_ceo_approval = 0
		approve_doc.save(ignore_permissions=True)
		apply_workflow(frappe.get_doc("Asset Request", approve_doc.name), "AR Submit for Approval")

		frappe.set_user(self.emp_user)
		try:
			with self.assertRaises(Exception):
				apply_workflow(frappe.get_doc("Asset Request", approve_doc.name), "AR Approve")
		finally:
			frappe.set_user("Administrator")

		frappe.set_user(self.mgr_user)
		try:
			apply_workflow(frappe.get_doc("Asset Request", approve_doc.name), "AR Approve")
		finally:
			frappe.set_user("Administrator")
		approve_doc.reload()
		self.assertEqual(approve_doc.docstatus, 1)
		self.assertEqual(approve_doc.workflow_state, "Approved")

		reject_doc = h.make_request(company_name=self.company, employee=self.employee, item_code=self.item)
		reject_doc.manager_approver = self.mgr_user
		reject_doc.require_planning_approval = 0
		reject_doc.require_ceo_approval = 0
		reject_doc.rejection_reason = "Not justified"
		reject_doc.save(ignore_permissions=True)
		apply_workflow(frappe.get_doc("Asset Request", reject_doc.name), "AR Submit for Approval")
		frappe.set_user(self.mgr_user)
		try:
			pending = frappe.get_doc("Asset Request", reject_doc.name)
			pending.rejection_reason = "Not justified"
			apply_workflow(pending, "AR Reject")
		finally:
			frappe.set_user("Administrator")
		reject_doc.reload()
		self.assertEqual(reject_doc.workflow_state, "Rejected")
		self.assertEqual(int(reject_doc.docstatus), 0)

	def test_planner_and_ceo_optional_approval(self):
		self._ready()
		from frappe.model.workflow import apply_workflow

		planner_doc = h.make_request(company_name=self.company, employee=self.employee, item_code=self.item)
		planner_doc.manager_approver = self.mgr_user
		planner_doc.planning_approver = self.planner_user
		planner_doc.require_planning_approval = 1
		planner_doc.require_ceo_approval = 0
		planner_doc.save(ignore_permissions=True)
		apply_workflow(frappe.get_doc("Asset Request", planner_doc.name), "AR Submit for Approval")
		frappe.set_user(self.mgr_user)
		try:
			apply_workflow(frappe.get_doc("Asset Request", planner_doc.name), "AR Approve")
		finally:
			frappe.set_user("Administrator")
		planner_doc.reload()
		self.assertEqual(planner_doc.workflow_state, "Pending Planning Approval")
		frappe.set_user(self.planner_user)
		try:
			apply_workflow(frappe.get_doc("Asset Request", planner_doc.name), "AR Approve")
		finally:
			frappe.set_user("Administrator")
		planner_doc.reload()
		self.assertEqual(planner_doc.docstatus, 1)
		self.assertEqual(planner_doc.workflow_state, "Approved")

		ceo_doc = h.make_request(company_name=self.company, employee=self.employee, item_code=self.item)
		ceo_doc.manager_approver = self.mgr_user
		ceo_doc.ceo_approver = self.ceo_user
		ceo_doc.require_planning_approval = 0
		ceo_doc.require_ceo_approval = 1
		ceo_doc.save(ignore_permissions=True)
		apply_workflow(frappe.get_doc("Asset Request", ceo_doc.name), "AR Submit for Approval")
		frappe.set_user(self.mgr_user)
		try:
			apply_workflow(frappe.get_doc("Asset Request", ceo_doc.name), "AR Approve")
		finally:
			frappe.set_user("Administrator")
		ceo_doc.reload()
		self.assertEqual(ceo_doc.workflow_state, "Pending CEO Approval")
		frappe.set_user(self.ceo_user)
		try:
			apply_workflow(frappe.get_doc("Asset Request", ceo_doc.name), "AR Approve")
		finally:
			frappe.set_user("Administrator")
		ceo_doc.reload()
		self.assertEqual(ceo_doc.docstatus, 1)
		self.assertEqual(ceo_doc.workflow_state, "Approved")

	def test_asset_manager_has_fulfillment_access(self):
		self._ready()
		doc = h.make_request(company_name=self.company, employee=self.employee, item_code=self.item)
		self.assertTrue(has_asset_request_permission(doc, user=self.am_user))
		self.assertEqual(asset_request_permission_query_conditions(self.am_user), "")
		frappe.set_user(self.am_user)
		try:
			self.assertTrue(frappe.has_permission("Asset Request", "write", doc=doc, user=self.am_user))
		finally:
			frappe.set_user("Administrator")
