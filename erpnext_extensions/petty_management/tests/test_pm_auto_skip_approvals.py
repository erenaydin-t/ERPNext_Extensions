# Copyright (c) 2026, ERPNext Extensions contributors
"""v4.1.4: consecutive same-user auto-skip + User-role action visibility."""

from __future__ import annotations

import frappe
from frappe.model.workflow import get_transitions
from frappe.tests.utils import FrappeTestCase
from frappe.utils import today

from erpnext_extensions.petty_management.services.workflow_utils import apply_pm_workflow
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
	have = {r.role for r in user.roles}
	for role in roles:
		if not frappe.db.exists("Role", role):
			frappe.get_doc({"doctype": "Role", "role_name": role}).insert(ignore_permissions=True)
		if role not in have:
			user.append("roles", {"role": role})
	# Drop deprecated functional roles so tests prove User/Accountant alone suffice.
	for legacy in ("Petty Management Manager", "Petty Management Admin", "Petty Management Auditor"):
		user.roles = [r for r in user.roles if r.role != legacy]
	user.save(ignore_permissions=True)
	frappe.db.commit()
	return email


def _wf_title(link: str | None) -> str:
	if not link:
		return ""
	return (frappe.db.get_value("Workflow State", link, "workflow_state_name") or link or "").strip()


def _open_todos(doctype: str, name: str) -> list[dict]:
	return frappe.get_all(
		"ToDo",
		filters={"reference_type": doctype, "reference_name": name, "status": "Open"},
		fields=["name", "allocated_to", "assignment_rule"],
	)


def _workflow_actions_for(doctype: str, name: str) -> list[str]:
	return sorted({t.get("action") for t in get_transitions(frappe.get_doc(doctype, name))})


def _version_count(doctype: str, name: str) -> int:
	return frappe.db.count("Version", {"ref_doctype": doctype, "docname": name})


def _workflow_action_count(doctype: str, name: str) -> int:
	return frappe.db.count(
		"Workflow Action",
		{"reference_doctype": doctype, "reference_name": name, "status": "Completed"},
	)


class TestPMAutoSkipApprovals(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		tpm._ensure_company_context()
		# Rebuild workflow to v4.1.4 role model for this site.
		from erpnext_extensions.patches.post_model_sync.migrate_pm_roles_autoskip_v414 import execute

		execute()

		cls.mgr = _ensure_user(
			"pm_autoskip_mgr@example.com",
			["Petty Management User", "Expense Approver", "Accounts User", "System Manager"],
		)
		cls.ceo = _ensure_user(
			"pm_autoskip_ceo@example.com",
			["Petty Management User", "Accounts User", "System Manager"],
		)
		cls.fin = _ensure_user(
			"pm_autoskip_fin@example.com",
			["Petty Management Accountant", "Accounts User", "System Manager"],
		)
		cls.mgr_ceo = _ensure_user(
			"pm_autoskip_mgr_ceo@example.com",
			["Petty Management User", "Expense Approver", "Accounts User", "System Manager"],
		)
		cls.mgr_ceo_fin = _ensure_user(
			"pm_autoskip_all@example.com",
			[
				"Petty Management User",
				"Petty Management Accountant",
				"Expense Approver",
				"Accounts User",
				"System Manager",
			],
		)

	def _configure(self, manager: str, ceo: str, finance: str) -> None:
		settings = frappe.get_single("PM Settings")
		settings.db_set("ceo_approver", ceo, update_modified=False)
		settings.db_set("finance_manager", finance, update_modified=False)
		settings.db_set("finance_supervisor", finance, update_modified=False)
		settings.db_set("require_named_manager_approver", 1, update_modified=False)

	def _new_pending_manager(self, manager: str, ceo: str, finance: str) -> str:
		self._configure(manager, ceo, finance)
		emp = tpm._make_employee()
		frappe.db.set_value("Employee", emp, "expense_approver", manager, update_modified=False)
		tpm._make_holder(emp)
		frappe.set_user("Administrator")
		req = frappe.new_doc("PM Request")
		req.company = tpm.COMPANY
		req.employee = emp
		req.transaction_date = today()
		req.append("details", {"description": "autoskip", "advance_amount": 15000})
		req.insert(ignore_permissions=True)
		apply_pm_workflow(req, "PM Submit for Approval")
		req.reload()
		self.assertEqual(_wf_title(req.workflow_state), "Pending Manager Approval")
		return req.name

	def test_manager_only_stops_at_ceo(self):
		name = self._new_pending_manager(self.mgr, self.ceo, self.fin)
		frappe.set_user(self.mgr)
		req = frappe.get_doc("PM Request", name)
		before_ver = _version_count("PM Request", name)
		apply_pm_workflow(req, "PM Manager Approve")
		req.reload()
		self.assertEqual(_wf_title(req.workflow_state), "Pending CEO Approval")
		self.assertGreaterEqual(_version_count("PM Request", name), before_ver)
		todos = _open_todos("PM Request", name)
		self.assertTrue(any(t.allocated_to == self.ceo for t in todos), msg=str(todos))
		self.assertFalse(any(t.allocated_to == self.mgr for t in todos))

	def test_ceo_only_stops_at_finance(self):
		name = self._new_pending_manager(self.mgr, self.ceo, self.fin)
		frappe.set_user(self.mgr)
		apply_pm_workflow(frappe.get_doc("PM Request", name), "PM Manager Approve")
		frappe.set_user(self.ceo)
		apply_pm_workflow(frappe.get_doc("PM Request", name), "PM CEO Approve")
		req = frappe.get_doc("PM Request", name)
		self.assertEqual(_wf_title(req.workflow_state), "Pending Finance Approval")
		todos = _open_todos("PM Request", name)
		self.assertTrue(any(t.allocated_to == self.fin for t in todos), msg=str(todos))

	def test_manager_equals_ceo_auto_skips_ceo(self):
		name = self._new_pending_manager(self.mgr_ceo, self.mgr_ceo, self.fin)
		frappe.set_user(self.mgr_ceo)
		before_actions = _workflow_action_count("PM Request", name)
		apply_pm_workflow(frappe.get_doc("PM Request", name), "PM Manager Approve")
		req = frappe.get_doc("PM Request", name)
		self.assertEqual(_wf_title(req.workflow_state), "Pending Finance Approval")
		# Manager + auto CEO = at least 2 completed workflow actions beyond submit.
		self.assertGreaterEqual(_workflow_action_count("PM Request", name), before_actions + 1)
		todos = _open_todos("PM Request", name)
		self.assertTrue(any(t.allocated_to == self.fin for t in todos), msg=str(todos))
		self.assertFalse(any(t.allocated_to == self.mgr_ceo for t in todos))

	def test_manager_ceo_finance_same_user_with_accountant(self):
		name = self._new_pending_manager(self.mgr_ceo_fin, self.mgr_ceo_fin, self.mgr_ceo_fin)
		frappe.set_user(self.mgr_ceo_fin)
		apply_pm_workflow(frappe.get_doc("PM Request", name), "PM Manager Approve")
		req = frappe.get_doc("PM Request", name)
		self.assertEqual(_wf_title(req.workflow_state), "Finance Approved")
		self.assertEqual(req.status, "Waiting for Payment")
		todos = _open_todos("PM Request", name)
		self.assertEqual(todos, [])

	def test_distinct_approvers_no_duplicate_auto_skip(self):
		name = self._new_pending_manager(self.mgr, self.ceo, self.fin)
		frappe.set_user(self.mgr)
		apply_pm_workflow(frappe.get_doc("PM Request", name), "PM Manager Approve")
		req = frappe.get_doc("PM Request", name)
		self.assertEqual(_wf_title(req.workflow_state), "Pending CEO Approval")
		# Manager must not see CEO Approve after hop (different stamp).
		frappe.set_user(self.mgr)
		self.assertNotIn("PM CEO Approve", _workflow_actions_for("PM Request", name))

	def test_action_visibility_user_role_stamped_manager(self):
		name = self._new_pending_manager(self.mgr, self.ceo, self.fin)
		frappe.set_user(self.mgr)
		actions = _workflow_actions_for("PM Request", name)
		self.assertIn("PM Manager Approve", actions)
		self.assertIn("PM Reject", actions)
		frappe.set_user(self.ceo)
		self.assertNotIn("PM Manager Approve", _workflow_actions_for("PM Request", name))

	def test_action_visibility_finance_requires_accountant(self):
		name = self._new_pending_manager(self.mgr, self.ceo, self.fin)
		frappe.set_user(self.mgr)
		apply_pm_workflow(frappe.get_doc("PM Request", name), "PM Manager Approve")
		frappe.set_user(self.ceo)
		apply_pm_workflow(frappe.get_doc("PM Request", name), "PM CEO Approve")
		# User without Accountant must not see Finance Approve even if somehow stamped.
		frappe.set_user(self.mgr)
		self.assertNotIn("PM Finance Approve", _workflow_actions_for("PM Request", name))
		frappe.set_user(self.fin)
		self.assertIn("PM Finance Approve", _workflow_actions_for("PM Request", name))

	def test_reject_never_auto_skipped(self):
		name = self._new_pending_manager(self.mgr_ceo, self.mgr_ceo, self.fin)
		frappe.set_user(self.mgr_ceo)
		apply_pm_workflow(frappe.get_doc("PM Request", name), "PM Reject")
		req = frappe.get_doc("PM Request", name)
		self.assertEqual(_wf_title(req.workflow_state), "Rejected")

	def test_clearance_manager_equals_finance_auto_skip(self):
		self._configure(self.mgr_ceo_fin, self.ceo, self.mgr_ceo_fin)
		emp = tpm._make_employee()
		frappe.db.set_value("Employee", emp, "expense_approver", self.mgr_ceo_fin, update_modified=False)
		tpm._make_holder(emp)
		pm_request, _pe = tpm._fund_pm_request(emp, 50_000.0)
		waiting = frappe.db.get_value("Workflow State", {"workflow_state_name": "Finance Approved"}, "name")
		frappe.db.set_value(
			"PM Request",
			pm_request,
			{"workflow_state": waiting, "status": "Paid", "payment_status": "Paid"},
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
		# Stamp both approvers to the same user for auto-skip.
		frappe.db.set_value(
			"PM Clearance",
			cl.name,
			{"manager_approver": self.mgr_ceo_fin, "finance_approver": self.mgr_ceo_fin},
			update_modified=False,
		)
		apply_pm_workflow(cl, "PM Submit Finance Review")
		frappe.set_user(self.mgr_ceo_fin)
		apply_pm_workflow(frappe.get_doc("PM Clearance", cl.name), "PM Manager Approve")
		cl = frappe.get_doc("PM Clearance", cl.name)
		self.assertEqual(_wf_title(cl.workflow_state), "Approved")

	def test_opening_advance_accountant_has_cancel_delete(self):
		"""Admin/Manager DocPerm moved: Accountant retains cancel/delete on Opening Advance."""
		from frappe import get_meta

		frappe.clear_cache(doctype="PM Opening Advance")
		meta = get_meta("PM Opening Advance")
		roles = {p.role: p for p in meta.permissions}
		self.assertNotIn("Petty Management Admin", roles)
		self.assertNotIn("Petty Management Manager", roles)
		self.assertNotIn("Petty Management Auditor", roles)
		acct = roles.get("Petty Management Accountant")
		self.assertTrue(acct)
		self.assertTrue(acct.cancel)
		self.assertTrue(acct.delete)
		self.assertTrue(acct.submit)
		sm = roles.get("System Manager")
		self.assertTrue(sm and sm.cancel and sm.delete)
