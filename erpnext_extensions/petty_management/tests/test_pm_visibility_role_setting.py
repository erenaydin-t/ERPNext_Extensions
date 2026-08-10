# Copyright (c) 2026, ERPNext Extensions contributors
"""v4.1.3: PM Settings.operational_pm_visibility_role drives unrestricted visibility."""

from __future__ import annotations

import unittest

import frappe
from frappe.utils.password import update_password

from erpnext_extensions.petty_management.permissions import (
	DEFAULT_OPERATIONAL_PM_VISIBILITY_ROLE,
	_is_pm_visibility_unrestricted,
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


def _set_visibility_role(role: str | None) -> None:
	frappe.db.set_single_value("PM Settings", "operational_pm_visibility_role", role or "")
	frappe.clear_cache(doctype="PM Settings")


class TestPMVisibilityRoleSetting(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")
		tpm._ensure_company_context()
		if not tpm.COMPANY:
			raise unittest.SkipTest("No company")
		if not frappe.get_meta("PM Settings").has_field("operational_pm_visibility_role"):
			raise unittest.SkipTest("operational_pm_visibility_role field missing — migrate first")

		cls._saved_role = frappe.db.get_single_value("PM Settings", "operational_pm_visibility_role")
		_set_visibility_role(DEFAULT_OPERATIONAL_PM_VISIBILITY_ROLE)

		cls.accountant = _make_user(
			"pm_viscfg_acct_v413@example.com",
			["Petty Management Accountant", "Accounts User"],
		)
		cls.manager = _make_user(
			"pm_viscfg_mgr_v413@example.com",
			["Petty Management Manager", "Petty Management User", "Accounts User"],
		)
		cls.holder = _make_user(
			"pm_viscfg_holder_v413@example.com",
			["Petty Management User", "Accounts User", "Employee"],
		)
		cls.mgr_approver = _make_user(
			"pm_viscfg_mgr_appr_v413@example.com",
			["Petty Management User", "Expense Approver", "Accounts User"],
		)
		cls.no_emp = _make_user(
			"pm_viscfg_noemp_v413@example.com",
			["Petty Management User", "Accounts User"],
		)
		frappe.db.sql("update `tabEmployee` set user_id=null where user_id=%s", cls.no_emp)
		frappe.db.sql("update `tabEmployee` set user_id=null where user_id=%s", cls.mgr_approver)
		frappe.db.sql("update `tabEmployee` set user_id=null where user_id=%s", cls.manager)
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
		cls.req.append("details", {"advance_amount": 1000, "description": "viscfg"})
		cls.req.insert(ignore_permissions=True)
		frappe.db.set_value(
			"PM Request",
			cls.req.name,
			{
				"docstatus": 1,
				"workflow_state": resolve_workflow_state_link("Waiting for Payment"),
				"status": "Waiting for Payment",
				"manager_approver": cls.mgr_approver,
			},
			update_modified=False,
		)

		cls.other_req = frappe.new_doc("PM Request")
		cls.other_req.company = tpm.COMPANY
		cls.other_req.employee = cls.other_emp
		cls.other_req.transaction_date = frappe.utils.today()
		cls.other_req.append("details", {"advance_amount": 2000, "description": "other"})
		cls.other_req.insert(ignore_permissions=True)

		cls.other_cl = frappe.new_doc("PM Clearance")
		cls.other_cl.company = tpm.COMPANY
		cls.other_cl.employee = cls.other_emp
		cls.other_cl.transaction_date = frappe.utils.today()
		cls.other_cl.flags.ignore_mandatory = True
		cls.other_cl.flags.ignore_validate = True
		cls.other_cl.insert(ignore_permissions=True)
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		_set_visibility_role(cls._saved_role or DEFAULT_OPERATIONAL_PM_VISIBILITY_ROLE)

	def setUp(self):
		frappe.set_user("Administrator")
		_set_visibility_role(DEFAULT_OPERATIONAL_PM_VISIBILITY_ROLE)

	def tearDown(self):
		frappe.set_user("Administrator")
		_set_visibility_role(DEFAULT_OPERATIONAL_PM_VISIBILITY_ROLE)

	def _names(self, doctype: str) -> set[str]:
		return {r["name"] for r in frappe.get_list(doctype, fields=["name"], limit_page_length=200)}

	def test_default_and_fallback(self):
		self.assertEqual(get_operational_pm_visibility_role(), DEFAULT_OPERATIONAL_PM_VISIBILITY_ROLE)
		_set_visibility_role("")
		self.assertEqual(get_operational_pm_visibility_role(), DEFAULT_OPERATIONAL_PM_VISIBILITY_ROLE)
		_set_visibility_role(None)
		self.assertEqual(get_operational_pm_visibility_role(), DEFAULT_OPERATIONAL_PM_VISIBILITY_ROLE)

	def test_settings_role_controls_unrestricted_visibility(self):
		self.assertTrue(_is_pm_visibility_unrestricted(self.accountant))
		self.assertFalse(_is_pm_visibility_unrestricted(self.manager))
		self.assertEqual(pm_request_permission_query_conditions(self.accountant), "")
		self.assertNotEqual(pm_request_permission_query_conditions(self.manager), "")

		_set_visibility_role("Petty Management Manager")
		self.assertEqual(get_operational_pm_visibility_role(), "Petty Management Manager")
		self.assertTrue(_is_pm_visibility_unrestricted(self.manager))
		self.assertFalse(_is_pm_visibility_unrestricted(self.accountant))
		self.assertEqual(pm_request_permission_query_conditions(self.manager), "")
		self.assertEqual(pm_clearance_permission_query_conditions(self.manager), "")
		self.assertNotEqual(pm_request_permission_query_conditions(self.accountant), "")

	def test_changing_role_immediately_changes_list_scope(self):
		frappe.set_user(self.manager)
		self.assertNotIn(self.other_req.name, self._names("PM Request"))
		self.assertNotIn(self.other_cl.name, self._names("PM Clearance"))

		frappe.set_user("Administrator")
		_set_visibility_role("Petty Management Manager")

		frappe.set_user(self.manager)
		self.assertIn(self.other_req.name, self._names("PM Request"))
		self.assertIn(self.other_cl.name, self._names("PM Clearance"))
		self.assertTrue(
			frappe.has_permission(
				"PM Request", "read", doc=frappe.get_doc("PM Request", self.other_req.name)
			)
		)

		frappe.set_user("Administrator")
		_set_visibility_role(DEFAULT_OPERATIONAL_PM_VISIBILITY_ROLE)

		frappe.set_user(self.manager)
		self.assertNotIn(self.other_req.name, self._names("PM Request"))
		frappe.set_user(self.accountant)
		self.assertIn(self.other_req.name, self._names("PM Request"))

	def test_administrator_unaffected_by_setting(self):
		_set_visibility_role("Petty Management Manager")
		self.assertTrue(_is_pm_visibility_unrestricted("Administrator"))
		self.assertEqual(pm_request_permission_query_conditions("Administrator"), "")
		_set_visibility_role("")
		self.assertTrue(_is_pm_visibility_unrestricted("Administrator"))

	def test_holder_approver_fail_closed_unchanged(self):
		_set_visibility_role("Petty Management Manager")
		# Holder still own-only (does not have Manager role)
		frappe.set_user(self.holder)
		self.assertIn(self.req.name, self._names("PM Request"))
		self.assertNotIn(self.other_req.name, self._names("PM Request"))

		# Named manager approver still assignment-scoped when Manager is unrestricted —
		# this user has Expense Approver / User only, not Manager role.
		frappe.set_user(self.mgr_approver)
		self.assertIn(self.req.name, self._names("PM Request"))
		self.assertNotIn(self.other_req.name, self._names("PM Request"))

		frappe.set_user(self.no_emp)
		self.assertEqual(self._names("PM Request"), set())
		self.assertEqual(self._names("PM Clearance"), set())
