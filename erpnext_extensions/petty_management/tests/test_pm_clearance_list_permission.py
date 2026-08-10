# Copyright (c) 2026, ERPNext Extensions contributors
"""v4.1.3: PM Clearance list/form permissions + named approver + no-employee fail-closed."""

from __future__ import annotations

import json
import unittest

import frappe
from frappe.utils.password import update_password

from erpnext_extensions.petty_management.permissions import (
	_petty_user_restricted,
	_user_employee,
	pm_clearance_permission_query_conditions,
	pm_request_permission_query_conditions,
)
from erpnext_extensions.petty_management.services.workflow_utils import resolve_workflow_state_link
from erpnext_extensions.petty_management.tests import test_pm_clearance as tpm

CLR_REPORTVIEW_FIELDS = [
	"`tabPM Clearance`.`name`",
	"`tabPM Clearance`.`holder`",
	"`tabPM Clearance`.`employee`",
	"`tabPM Clearance`.`employee_name`",
	"holder.employee_name as holder_employee_name",
	"employee.employee_name as employee_employee_name",
]


def _ensure_role(role: str) -> None:
	if not frappe.db.exists("Role", role):
		frappe.get_doc({"doctype": "Role", "role_name": role}).insert(ignore_permissions=True)


def _make_user(email: str, roles: list[str], password: str = "pm_sec_test_1") -> str:
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
	update_password(email, password)
	user = frappe.get_doc("User", email)
	user.roles = []
	for role in roles:
		_ensure_role(role)
		user.append("roles", {"role": role})
	user.enabled = 1
	user.save(ignore_permissions=True)
	frappe.db.commit()
	return email


def _insert_clearance(employee: str, *, manager: str, finance: str) -> str:
	cl = frappe.new_doc("PM Clearance")
	cl.company = tpm.COMPANY
	cl.employee = employee
	cl.transaction_date = frappe.utils.today()
	cl.flags.ignore_mandatory = True
	cl.flags.ignore_validate = True
	cl.insert(ignore_permissions=True)
	frappe.db.set_value(
		"PM Clearance",
		cl.name,
		{
			"manager_approver": manager,
			"finance_approver": finance,
			"workflow_state": resolve_workflow_state_link("Pending Manager Approval")
			or "Pending Manager Approval",
			"status": "Pending Approval",
			"docstatus": 1,
		},
		update_modified=False,
	)
	frappe.db.commit()
	return cl.name


class TestPMClearanceListPermission(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")
		tpm._ensure_company_context()
		if not tpm.COMPANY:
			raise unittest.SkipTest("No company")

		cls.holder = _make_user(
			"pm_clr_list_holder_v413@example.com",
			["Petty Management User", "Accounts User", "Employee"],
		)
		cls.manager_named = _make_user(
			"pm_clr_list_mgr_named_v413@example.com",
			["Petty Management User", "Expense Approver", "Accounts User"],
		)
		cls.finance_named = _make_user(
			"pm_clr_list_fin_named_v413@example.com",
			["Petty Management User", "Accounts User"],
		)
		cls.finance_elev = _make_user(
			"pm_clr_list_fin_elev_v413@example.com",
			["Petty Management Accountant", "Accounts User"],
		)
		cls.manager_elev = _make_user(
			"pm_clr_list_mgr_elev_v413@example.com",
			["Petty Management Manager", "Petty Management User", "Accounts User"],
		)
		cls.no_emp = _make_user(
			"pm_clr_list_noemp_v413@example.com",
			["Petty Management User", "Accounts User"],
		)
		frappe.db.sql("update `tabEmployee` set user_id=null where user_id=%s", cls.no_emp)
		frappe.db.commit()

		cls.emp = tpm._make_employee()
		frappe.db.set_value("Employee", cls.emp, "user_id", cls.holder, update_modified=False)
		tpm._make_holder(cls.emp)

		cls.other_emp = tpm._make_employee()
		tpm._make_holder(cls.other_emp)

		cls.own_clr = _insert_clearance(
			cls.emp, manager=cls.manager_named, finance=cls.finance_named
		)
		cls.other_clr = _insert_clearance(
			cls.other_emp, manager=cls.manager_elev, finance=cls.finance_elev
		)

	def setUp(self):
		frappe.set_user("Administrator")

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_no_employee_fail_closed_without_sql_error(self):
		self.assertTrue(_petty_user_restricted(self.no_emp))
		self.assertIsNone(_user_employee(self.no_emp))
		cond = pm_clearance_permission_query_conditions(self.no_emp)
		self.assertIn("manager_approver", cond)
		frappe.set_user(self.no_emp)
		rows = frappe.get_list("PM Clearance", fields=CLR_REPORTVIEW_FIELDS, limit_page_length=20)
		self.assertEqual(rows, [])
		req_rows = frappe.get_list("PM Request", fields=["name"], limit_page_length=20)
		self.assertEqual(req_rows, [])

	def test_holder_clearance_list_and_form_scoped(self):
		frappe.set_user(self.holder)
		rows = frappe.get_list("PM Clearance", fields=CLR_REPORTVIEW_FIELDS, limit_page_length=50)
		names = {r["name"] for r in rows}
		self.assertIn(self.own_clr, names)
		self.assertNotIn(self.other_clr, names)
		self.assertTrue(frappe.has_permission("PM Clearance", "read", doc=frappe.get_doc("PM Clearance", self.own_clr)))
		self.assertFalse(
			frappe.has_permission("PM Clearance", "read", doc=frappe.get_doc("PM Clearance", self.other_clr))
		)

	def test_named_manager_approver_can_access_assigned_clearance(self):
		self.assertTrue(_petty_user_restricted(self.manager_named))
		self.assertIsNone(_user_employee(self.manager_named))
		cond = pm_clearance_permission_query_conditions(self.manager_named)
		self.assertIn("manager_approver", cond)
		self.assertNotEqual(cond, "1=0")

		frappe.set_user(self.manager_named)
		rows = frappe.get_list("PM Clearance", fields=CLR_REPORTVIEW_FIELDS, limit_page_length=50)
		names = {r["name"] for r in rows}
		self.assertIn(self.own_clr, names)
		self.assertNotIn(self.other_clr, names)
		self.assertTrue(
			frappe.has_permission("PM Clearance", "read", doc=frappe.get_doc("PM Clearance", self.own_clr))
		)

	def test_named_finance_approver_can_access_assigned_clearance(self):
		self.assertTrue(_petty_user_restricted(self.finance_named))
		frappe.set_user(self.finance_named)
		rows = frappe.get_list("PM Clearance", fields=["name"], limit_page_length=50)
		names = {r["name"] for r in rows}
		self.assertIn(self.own_clr, names)
		self.assertNotIn(self.other_clr, names)
		self.assertTrue(
			frappe.has_permission("PM Clearance", "read", doc=frappe.get_doc("PM Clearance", self.own_clr))
		)

	def test_accountant_unrestricted_manager_role_is_scoped(self):
		from erpnext_extensions.petty_management.permissions import _is_pm_visibility_unrestricted

		self.assertTrue(_is_pm_visibility_unrestricted(self.finance_elev))
		self.assertEqual(pm_clearance_permission_query_conditions(self.finance_elev), "")
		self.assertFalse(_is_pm_visibility_unrestricted(self.manager_elev))
		self.assertNotEqual(pm_clearance_permission_query_conditions(self.manager_elev), "")

		frappe.set_user(self.finance_elev)
		rows = frappe.get_list("PM Clearance", fields=["name"], limit_page_length=200)
		names = {r["name"] for r in rows}
		self.assertIn(self.own_clr, names)
		self.assertIn(self.other_clr, names)

		# Manager role alone: only docs where stamped (none for other_clr unless stamped)
		frappe.set_user(self.manager_elev)
		rows = frappe.get_list("PM Clearance", fields=["name"], limit_page_length=200)
		names = {r["name"] for r in rows}
		self.assertNotIn(self.own_clr, names)
		self.assertIn(self.other_clr, names)  # stamped manager_approver on other_clr


	def test_clearance_reportview_for_restricted_holder(self):
		frappe.set_user(self.holder)
		frappe.local.form_dict = frappe._dict(
			{
				"doctype": "PM Clearance",
				"fields": json.dumps(CLR_REPORTVIEW_FIELDS),
				"filters": "[]",
				"order_by": "`tabPM Clearance`.`modified` desc",
				"start": 0,
				"page_length": 40,
				"view": "List",
			}
		)
		out = frappe.call("frappe.desk.reportview.get")
		idx = out["keys"].index("name")
		names = {row[idx] for row in out["values"]}
		self.assertIn(self.own_clr, names)
		self.assertNotIn(self.other_clr, names)
		for key in ("employee", "holder", "employee_name"):
			self.assertIn(key, out["keys"])
