# Copyright (c) 2026, ERPNext Extensions contributors
"""v4.1.3: PM visibility — Accountant unrestricted; others scoped."""

from __future__ import annotations

import unittest

import frappe
from frappe.utils.password import update_password

from erpnext_extensions.petty_management.permissions import (
	DEFAULT_OPERATIONAL_PM_VISIBILITY_ROLE,
	_is_pm_visibility_unrestricted,
	_petty_user_restricted,
	_user_employee,
	get_operational_pm_visibility_role,
	pm_clearance_permission_query_conditions,
	pm_request_permission_query_conditions,
)
from erpnext_extensions.petty_management.services.workflow_utils import resolve_workflow_state_link
from erpnext_extensions.petty_management.tests import test_pm_clearance as tpm


def _ensure_role(role: str) -> None:
	if not frappe.db.exists("Role", role):
		frappe.get_doc({"doctype": "Role", "role_name": role}).insert(ignore_permissions=True)


def _make_user(email: str, roles: list[str]) -> str:
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": email.split("@")[0][:30],
				"send_welcome_email": 0,
				"user_type": "System User",
			}
		).insert(ignore_permissions=True)
	update_password(email, "pm_sec_test_1")
	user = frappe.get_doc("User", email)
	user.roles = []
	for role in roles:
		_ensure_role(role)
		user.append("roles", {"role": role})
	user.enabled = 1
	user.save(ignore_permissions=True)
	frappe.db.commit()
	return email


class TestPMVisibilityRoles(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")
		tpm._ensure_company_context()
		if not tpm.COMPANY:
			raise unittest.SkipTest("No company")

		cls.holder = _make_user(
			"pm_vis_holder_v413@example.com",
			["Petty Management User", "Accounts User", "Employee"],
		)
		cls.accountant = _make_user(
			"pm_vis_accountant_v413@example.com",
			[DEFAULT_OPERATIONAL_PM_VISIBILITY_ROLE, "Accounts User"],
		)
		cls.manager_only = _make_user(
			"pm_vis_manager_only_v413@example.com",
			["Petty Management Manager", "Petty Management User", "Accounts User"],
		)
		cls.admin_only = _make_user(
			"pm_vis_admin_only_v413@example.com",
			["Petty Management Admin", "Accounts User"],
		)
		cls.auditor_only = _make_user(
			"pm_vis_auditor_only_v413@example.com",
			["Petty Management Auditor", "Accounts User"],
		)
		cls.mgr_approver = _make_user(
			"pm_vis_mgr_appr_v413@example.com",
			["Petty Management User", "Expense Approver", "Accounts User"],
		)
		cls.ceo_approver = _make_user(
			"pm_vis_ceo_appr_v413@example.com",
			["Petty Management User", "Petty Management Manager", "Accounts User"],
		)
		cls.fin_approver = _make_user(
			"pm_vis_fin_appr_v413@example.com",
			["Petty Management User", "Accounts User"],
		)
		cls.unrelated = _make_user(
			"pm_vis_unrelated_v413@example.com",
			["Petty Management User", "Accounts User"],
		)
		cls.no_emp = _make_user(
			"pm_vis_noemp_v413@example.com",
			["Petty Management User", "Accounts User"],
		)
		frappe.db.sql("update `tabEmployee` set user_id=null where user_id=%s", cls.no_emp)
		frappe.db.sql("update `tabEmployee` set user_id=null where user_id=%s", cls.unrelated)
		frappe.db.sql("update `tabEmployee` set user_id=null where user_id=%s", cls.mgr_approver)
		frappe.db.sql("update `tabEmployee` set user_id=null where user_id=%s", cls.ceo_approver)
		frappe.db.sql("update `tabEmployee` set user_id=null where user_id=%s", cls.fin_approver)
		frappe.db.commit()

		cls.emp = tpm._make_employee()
		frappe.db.set_value("Employee", cls.emp, "user_id", cls.holder, update_modified=False)
		tpm._make_holder(cls.emp)
		cls.other_emp = tpm._make_employee()
		tpm._make_holder(cls.other_emp)

		cls.req = frappe.new_doc("PM Request")
		cls.req.company = tpm.COMPANY
		cls.req.employee = cls.emp
		cls.req.transaction_date = frappe.utils.today()
		cls.req.append("details", {"advance_amount": 1000, "description": "vis"})
		cls.req.insert(ignore_permissions=True)
		waiting = resolve_workflow_state_link("Waiting for Payment")
		frappe.db.set_value(
			"PM Request",
			cls.req.name,
			{
				"docstatus": 1,
				"workflow_state": waiting,
				"status": "Waiting for Payment",
				"manager_approver": cls.mgr_approver,
				"ceo_approver": cls.ceo_approver,
				"finance_approver": cls.fin_approver,
			},
			update_modified=False,
		)

		cls.other_req = frappe.new_doc("PM Request")
		cls.other_req.company = tpm.COMPANY
		cls.other_req.employee = cls.other_emp
		cls.other_req.transaction_date = frappe.utils.today()
		cls.other_req.append("details", {"advance_amount": 2000, "description": "other"})
		cls.other_req.insert(ignore_permissions=True)

		cls.cl = frappe.new_doc("PM Clearance")
		cls.cl.company = tpm.COMPANY
		cls.cl.employee = cls.emp
		cls.cl.transaction_date = frappe.utils.today()
		cls.cl.flags.ignore_mandatory = True
		cls.cl.flags.ignore_validate = True
		cls.cl.insert(ignore_permissions=True)
		frappe.db.set_value(
			"PM Clearance",
			cls.cl.name,
			{
				"manager_approver": cls.mgr_approver,
				"finance_approver": cls.fin_approver,
				"docstatus": 1,
				"workflow_state": resolve_workflow_state_link("Pending Manager Approval")
				or "Pending Manager Approval",
				"status": "Pending Approval",
			},
			update_modified=False,
		)
		cls.other_cl = frappe.new_doc("PM Clearance")
		cls.other_cl.company = tpm.COMPANY
		cls.other_cl.employee = cls.other_emp
		cls.other_cl.transaction_date = frappe.utils.today()
		cls.other_cl.flags.ignore_mandatory = True
		cls.other_cl.flags.ignore_validate = True
		cls.other_cl.insert(ignore_permissions=True)
		frappe.db.commit()

	def setUp(self):
		frappe.set_user("Administrator")

	def tearDown(self):
		frappe.set_user("Administrator")

	def _names(self, doctype: str) -> set[str]:
		return {r["name"] for r in frappe.get_list(doctype, fields=["name"], limit_page_length=200)}

	def test_operational_role_default(self):
		self.assertEqual(DEFAULT_OPERATIONAL_PM_VISIBILITY_ROLE, "Petty Management Accountant")
		self.assertEqual(get_operational_pm_visibility_role(), "Petty Management Accountant")

	def test_administrator_unrestricted(self):
		self.assertTrue(_is_pm_visibility_unrestricted("Administrator"))
		self.assertEqual(pm_request_permission_query_conditions("Administrator"), "")
		self.assertEqual(pm_clearance_permission_query_conditions("Administrator"), "")

	def test_accountant_unrestricted_like_administrator(self):
		self.assertTrue(_is_pm_visibility_unrestricted(self.accountant))
		self.assertFalse(_petty_user_restricted(self.accountant))
		self.assertEqual(pm_request_permission_query_conditions(self.accountant), "")
		self.assertEqual(pm_clearance_permission_query_conditions(self.accountant), "")
		frappe.set_user(self.accountant)
		req_names = self._names("PM Request")
		clr_names = self._names("PM Clearance")
		self.assertIn(self.req.name, req_names)
		self.assertIn(self.other_req.name, req_names)
		self.assertIn(self.cl.name, clr_names)
		self.assertIn(self.other_cl.name, clr_names)
		self.assertTrue(frappe.has_permission("PM Request", "read", doc=frappe.get_doc("PM Request", self.other_req.name)))
		self.assertTrue(frappe.has_permission("PM Clearance", "read", doc=frappe.get_doc("PM Clearance", self.other_cl.name)))

	def test_manager_admin_auditor_are_not_visibility_unrestricted(self):
		for u in (self.manager_only, self.admin_only, self.auditor_only):
			self.assertFalse(_is_pm_visibility_unrestricted(u), u)
			self.assertNotEqual(pm_request_permission_query_conditions(u), "")
		# Manager-only without stamps / employee → cannot see holder's other docs
		frappe.set_user(self.manager_only)
		names = self._names("PM Request")
		self.assertNotIn(self.req.name, names)
		self.assertNotIn(self.other_req.name, names)

	def test_holder_own_only(self):
		self.assertTrue(_petty_user_restricted(self.holder))
		frappe.set_user(self.holder)
		self.assertIn(self.req.name, self._names("PM Request"))
		self.assertNotIn(self.other_req.name, self._names("PM Request"))
		self.assertIn(self.cl.name, self._names("PM Clearance"))
		self.assertNotIn(self.other_cl.name, self._names("PM Clearance"))

	def test_manager_approver_assigned_only(self):
		frappe.set_user(self.mgr_approver)
		self.assertIn(self.req.name, self._names("PM Request"))
		self.assertNotIn(self.other_req.name, self._names("PM Request"))
		self.assertIn(self.cl.name, self._names("PM Clearance"))
		self.assertNotIn(self.other_cl.name, self._names("PM Clearance"))

	def test_ceo_approver_assigned_request_only(self):
		frappe.set_user(self.ceo_approver)
		self.assertIn(self.req.name, self._names("PM Request"))
		self.assertNotIn(self.other_req.name, self._names("PM Request"))
		# Clearance has no ceo_approver — CEO manager role alone does not unlock clearance
		self.assertNotIn(self.cl.name, self._names("PM Clearance"))

	def test_finance_approver_assigned_only(self):
		frappe.set_user(self.fin_approver)
		self.assertIn(self.req.name, self._names("PM Request"))
		self.assertNotIn(self.other_req.name, self._names("PM Request"))
		self.assertIn(self.cl.name, self._names("PM Clearance"))
		self.assertNotIn(self.other_cl.name, self._names("PM Clearance"))

	def test_unrelated_and_no_employee_fail_closed(self):
		self.assertIsNone(_user_employee(self.no_emp))
		for u in (self.unrelated, self.no_emp):
			frappe.set_user(u)
			self.assertEqual(self._names("PM Request"), set())
			self.assertEqual(self._names("PM Clearance"), set())
			self.assertFalse(
				frappe.has_permission("PM Request", "read", doc=frappe.get_doc("PM Request", self.req.name))
			)
