# Copyright (c) 2026, ERPNext Extensions contributors
"""v4.1.3: PM Request list / permission query must not SELECT missing User.employee."""

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
from erpnext_extensions.petty_management.tests import test_pm_clearance as tpm

REPORTVIEW_FIELDS = [
	"`tabPM Request`.`name`",
	"`tabPM Request`.`holder`",
	"`tabPM Request`.`employee`",
	"`tabPM Request`.`employee_name`",
	"holder.employee_name as holder_employee_name",
	"employee.employee_name as employee_employee_name",
]


def _ensure_role(role: str) -> None:
	if not frappe.db.exists("Role", role):
		frappe.get_doc({"doctype": "Role", "role_name": role}).insert(ignore_permissions=True)


def _make_user(email: str, roles: list[str], password: str = "pm_sec_test_1") -> str:
	_ensure_role("Petty Management User")
	_ensure_role("Petty Management Manager")
	if not frappe.db.exists("User", email):
		u = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": email.split("@")[0][:30],
				"send_welcome_email": 0,
				"user_type": "System User",
			}
		)
		u.insert(ignore_permissions=True)
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


def _make_owned_request(user_email: str) -> tuple[str, str]:
	emp = tpm._make_employee()
	frappe.db.set_value("Employee", emp, "user_id", user_email, update_modified=False)
	tpm._make_holder(emp)
	req = frappe.new_doc("PM Request")
	req.company = tpm.COMPANY
	req.employee = emp
	req.transaction_date = frappe.utils.today()
	req.append("details", {"advance_amount": 1500, "description": "v413 list perm"})
	req.insert(ignore_permissions=True)
	frappe.db.commit()
	return req.name, emp


class TestPMRequestListPermissionQuery(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")
		tpm._ensure_company_context()
		if not tpm.COMPANY:
			raise unittest.SkipTest("No company")
		cls.user_a = _make_user(
			"pm_list_user_a_v413@example.com",
			["Petty Management User", "Accounts User", "Employee"],
		)
		cls.user_b = _make_user(
			"pm_list_mgr_b_v413@example.com",
			["Petty Management Manager", "Petty Management User", "Accounts User"],
		)
		cls.own_name, cls.own_emp = _make_owned_request(cls.user_a)
		cls.other_name, cls.other_emp = _make_owned_request(
			_make_user(
				"pm_list_other_v413@example.com",
				["Petty Management User", "Accounts User", "Employee"],
			)
		)

	def setUp(self):
		frappe.set_user("Administrator")

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_user_employee_resolves_via_employee_user_id(self):
		self.assertTrue(_petty_user_restricted(self.user_a))
		self.assertEqual(_user_employee(self.user_a), self.own_emp)
		# Site may lack User.employee (HRMS uses Employee.user_id); must not raise.
		_ = _user_employee(self.user_a)

	def test_permission_query_scopes_employee(self):
		cond = pm_request_permission_query_conditions(self.user_a)
		self.assertIn(self.own_emp, cond)
		self.assertIn("`tabPM Request`.employee", cond)
		self.assertEqual(pm_request_permission_query_conditions("Administrator"), "")
		self.assertEqual(pm_request_permission_query_conditions(self.user_b), "")
		clr = pm_clearance_permission_query_conditions(self.user_a)
		self.assertIn(self.own_emp, clr)

	def test_restricted_user_get_list_no_sql_error_and_scoped(self):
		frappe.set_user(self.user_a)
		rows = frappe.get_list("PM Request", fields=REPORTVIEW_FIELDS, limit_page_length=100)
		names = {r["name"] for r in rows}
		self.assertIn(self.own_name, names)
		self.assertNotIn(self.other_name, names)

	def test_manager_get_list_no_sql_error(self):
		frappe.set_user(self.user_b)
		rows = frappe.get_list("PM Request", fields=REPORTVIEW_FIELDS, limit_page_length=20)
		self.assertIsInstance(rows, list)
		self.assertGreaterEqual(len(rows), 1)

	def test_administrator_get_list_no_regression(self):
		frappe.set_user("Administrator")
		rows = frappe.get_list("PM Request", fields=REPORTVIEW_FIELDS, limit_page_length=5)
		self.assertIsInstance(rows, list)

	def test_reportview_path_for_restricted_user(self):
		frappe.set_user(self.user_a)
		frappe.local.form_dict = frappe._dict(
			{
				"doctype": "PM Request",
				"fields": json.dumps(REPORTVIEW_FIELDS),
				"filters": "[]",
				"order_by": "`tabPM Request`.`modified` desc",
				"start": 0,
				"page_length": 40,
				"view": "List",
			}
		)
		out = frappe.call("frappe.desk.reportview.get")
		self.assertIn("keys", out)
		self.assertIn("values", out)
		idx = out["keys"].index("name")
		names = {row[idx] for row in out["values"]}
		self.assertIn(self.own_name, names)
		self.assertNotIn(self.other_name, names)
		# Display fields usable when present
		for key in ("employee", "holder", "employee_name"):
			self.assertIn(key, out["keys"])

	def test_named_manager_approver_sees_assigned_request(self):
		mgr = _make_user(
			"pm_list_named_mgr_v413@example.com",
			["Petty Management User", "Expense Approver", "Accounts User"],
		)
		frappe.db.set_value(
			"PM Request",
			self.own_name,
			"manager_approver",
			mgr,
			update_modified=False,
		)
		frappe.db.commit()
		self.assertTrue(_petty_user_restricted(mgr))
		self.assertIsNone(_user_employee(mgr))
		frappe.set_user(mgr)
		rows = frappe.get_list("PM Request", fields=REPORTVIEW_FIELDS, limit_page_length=50)
		names = {r["name"] for r in rows}
		self.assertIn(self.own_name, names)
		self.assertNotIn(self.other_name, names)

	def test_no_employee_user_fail_closed(self):
		no_emp = _make_user(
			"pm_list_noemp_req_v413@example.com",
			["Petty Management User", "Accounts User"],
		)
		frappe.db.sql("update `tabEmployee` set user_id=null where user_id=%s", no_emp)
		frappe.db.commit()
		self.assertIsNone(_user_employee(no_emp))
		frappe.set_user(no_emp)
		rows = frappe.get_list("PM Request", fields=REPORTVIEW_FIELDS, limit_page_length=20)
		self.assertEqual(rows, [])
