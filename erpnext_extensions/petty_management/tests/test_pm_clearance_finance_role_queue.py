# Copyright (c) 2026, ERPNext Extensions contributors
"""v4.5.3 Phase 1 (test-first): PM Clearance Finance Review Role Queue.

Target architecture (not yet implemented):
- PM Settings.clearance_finance_review_role → native Workflow Action role queue
- Any enabled user with the review role may Finance Approve/Reject
- finance_approver stamped only after successful Finance act (audit)
- No Assignment Rule for Clearance Finance Review

Run::

    bench --site development.localhost run-tests \\
        --module erpnext_extensions.petty_management.tests.test_pm_clearance_finance_role_queue \\
        --skip-before-tests

Uses ``unittest.TestCase`` + lazy ``test_pm_clearance`` helpers (avoids ERPNext BootStrapTestData).
"""

from __future__ import annotations

import unittest

import frappe
from frappe.exceptions import ValidationError
from frappe.model.workflow import WorkflowPermissionError
from frappe.utils import cint, flt, today
from frappe.utils.password import update_password

from erpnext_extensions.petty_management.permissions import (
	DEFAULT_OPERATIONAL_PM_VISIBILITY_ROLE,
	_is_pm_visibility_unrestricted,
	pm_clearance_permission_query_conditions,
)
from erpnext_extensions.petty_management.services.workflow_utils import apply_pm_workflow
from erpnext_extensions.petty_management.tests import test_pm_clearance as tpm

REVIEWER_ROLE = "Petty Management Clearance Reviewer"
FINANCE_ASSIGNMENT_RULE = "PM Clearance Finance Review"
MANAGER_ASSIGNMENT_RULE = "PM Clearance Manager Approval"


def _wf_title(link: str | None) -> str:
	if not link:
		return ""
	return (frappe.db.get_value("Workflow State", link, "workflow_state_name") or link or "").strip()


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


def _require_clearance_finance_review_role_field() -> None:
	meta = frappe.get_meta("PM Settings")
	if not meta.has_field("clearance_finance_review_role"):
		raise AssertionError(
			"PM Settings.clearance_finance_review_role is missing (v4.5.3 not implemented)"
		)


def _get_clearance_finance_review_role() -> str:
	from erpnext_extensions.petty_management.services.clearance_finance_review import (
		get_clearance_finance_review_role,
	)

	return get_clearance_finance_review_role()


def _configure_role_queue_settings(*, review_role: str = REVIEWER_ROLE) -> None:
	"""Configure PM Settings role queue (requires v4.5.3 schema + service)."""
	_require_clearance_finance_review_role_field()
	_ensure_role(review_role)
	settings = frappe.get_single("PM Settings")
	settings.db_set("clearance_finance_review_role", review_role, update_modified=False)
	frappe.db.commit()


def _prepare_role_queue_scenario() -> None:
	"""Ensure review role exists; configure settings when the field is already present."""
	_ensure_role(REVIEWER_ROLE)
	meta = frappe.get_meta("PM Settings")
	if meta.has_field("clearance_finance_review_role"):
		settings = frappe.get_single("PM Settings")
		settings.db_set("clearance_finance_review_role", REVIEWER_ROLE, update_modified=False)
		frappe.db.commit()


def _open_workflow_actions(cl_name: str) -> list[dict]:
	actions = frappe.get_all(
		"Workflow Action",
		filters={
			"reference_doctype": "PM Clearance",
			"reference_name": cl_name,
			"status": "Open",
		},
		fields=["name", "status", "user", "workflow_state"],
	)
	for row in actions:
		row["permitted_roles"] = frappe.get_all(
			"Workflow Action Permitted Role",
			filters={"parent": row["name"]},
			pluck="role",
		)
	return actions


def _open_finance_todos(cl_name: str) -> list[dict]:
	return frappe.get_all(
		"ToDo",
		filters={
			"reference_type": "PM Clearance",
			"reference_name": cl_name,
			"status": "Open",
		},
		fields=["name", "allocated_to", "assignment_rule"],
	)


def _finance_transition_uses_named_user_condition() -> bool:
	wf_name = frappe.db.get_value(
		"Workflow", {"document_type": "PM Clearance", "is_active": 1}, "name"
	)
	if not wf_name:
		return False
	for row in frappe.get_all(
		"Workflow Transition",
		filters={"parent": wf_name, "action": "PM Finance Approve"},
		fields=["condition", "state"],
	):
		state_title = _wf_title(row.get("state"))
		if state_title == "Pending Finance Review":
			cond = (row.get("condition") or "").strip()
			if "finance_approver" in cond and "session.user" in cond:
				return True
	return False


class TestPMClearanceFinanceRoleQueue(unittest.TestCase):
	"""Role-queue contract for PM Clearance Finance Review (v4.5.3)."""

	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")
		tpm._ensure_company_context()
		if not tpm.COMPANY:
			raise unittest.SkipTest("No company on site")

		from erpnext_extensions.patches.post_model_sync.migrate_pm_clearance_finance_role_queue_v453 import (
			execute as migrate_clearance_finance_role_queue_v453,
		)

		migrate_clearance_finance_role_queue_v453()

		cls.manager = _make_user(
			"pm_clr_rq_mgr_v453@example.com",
			["Petty Management User", "Expense Approver", "Accounts User"],
		)
		cls.reviewer_a = _make_user(
			"pm_clr_rq_rev_a_v453@example.com",
			[REVIEWER_ROLE, "Accounts User"],
		)
		cls.reviewer_b = _make_user(
			"pm_clr_rq_rev_b_v453@example.com",
			[REVIEWER_ROLE, "Accounts User"],
		)
		cls.unrelated_user = _make_user(
			"pm_clr_rq_unrelated_v453@example.com",
			["Petty Management User", "Accounts User"],
		)
		cls.request_finance = _make_user(
			"pm_clr_rq_req_fin_v453@example.com",
			["Petty Management Accountant", "Accounts User", "System Manager"],
		)
		cls.accountant = _make_user(
			"pm_clr_rq_accountant_v453@example.com",
			[DEFAULT_OPERATIONAL_PM_VISIBILITY_ROLE, "Accounts User"],
		)

		settings = frappe.get_single("PM Settings")
		settings.db_set("ceo_approver", "Administrator", update_modified=False)
		settings.db_set("finance_manager", cls.request_finance, update_modified=False)
		settings.db_set("require_named_manager_approver", 1, update_modified=False)
		frappe.db.commit()

		cls._created: list[tuple[str, str]] = []

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		settings = frappe.get_single("PM Settings")
		settings.db_set("finance_manager", cls.request_finance, update_modified=False)
		frappe.db.commit()

	def setUp(self):
		frappe.set_user("Administrator")
		settings = frappe.get_single("PM Settings")
		if not getattr(settings, "finance_manager", None):
			settings.db_set("finance_manager", self.request_finance, update_modified=False)
			frappe.db.commit()

	def tearDown(self):
		frappe.set_user("Administrator")

	def _track(self, dt: str, name: str) -> None:
		self.__class__._created.append((dt, name))

	def _funded_holder(self, amount: float = 50_000.0) -> tuple[str, str]:
		emp = tpm._make_employee()
		frappe.db.set_value("Employee", emp, "expense_approver", self.manager, update_modified=False)
		tpm._make_holder(emp)
		req, pe = tpm._fund_pm_request(emp, amount)
		self._track("Payment Entry", pe)
		self._track("PM Request", req)
		self._track("Employee", emp)
		from erpnext_extensions.petty_management.services.workflow_utils import resolve_workflow_state_link

		fa = resolve_workflow_state_link("Finance Approved")
		frappe.db.set_value(
			"PM Request",
			req,
			{"workflow_state": fa, "status": "Paid", "payment_status": "Paid"},
			update_modified=False,
		)
		return emp, req

	def _insert_submitted_pi(self, amount: float = 5_000.0) -> str:
		pi = tpm._make_pi_outstanding(amount)
		pi.insert(ignore_permissions=True)
		self._track("Purchase Invoice", pi.name)
		pi.submit()
		return pi.name

	def _insert_draft_pi(self, amount: float = 5_000.0) -> str:
		pi = tpm._make_pi_outstanding(amount)
		pi.insert(ignore_permissions=True)
		self._track("Purchase Invoice", pi.name)
		self.assertEqual(cint(pi.docstatus), 0)
		return pi.name

	def _new_clearance_with_pi(
		self, emp: str, req: str, pi_name: str, allocated: float | None = None
	) -> str:
		pi = frappe.get_doc("Purchase Invoice", pi_name)
		alloc = flt(allocated)
		if alloc <= 0:
			alloc = flt(pi.outstanding_amount if cint(pi.docstatus) == 1 else pi.grand_total)
		cl = frappe.new_doc("PM Clearance")
		cl.company = tpm.COMPANY
		cl.employee = emp
		cl.posting_date = today()
		cl.transaction_date = today()
		tpm._append_pm_clearance_detail_row(
			cl,
			{
				"settlement_type": "Purchase Invoice",
				"purchase_invoice": pi_name,
				"allocated_amount": alloc,
			},
		)
		cl.append(
			"request_allocations",
			{
				"funding_source_type": "PM Request",
				"pm_request": req,
				"allocated_amount": alloc,
			},
		)
		cl.insert(ignore_permissions=True)
		self._track("PM Clearance", cl.name)
		return cl.name

	def _advance_to_pending_finance(
		self,
		cl_name: str,
		*,
		finance_approver: str | None = None,
		clear_finance_stamp: bool = False,
	) -> None:
		"""Manager path to Pending Finance Review; optional finance stamp control."""
		if finance_approver is not None:
			frappe.db.set_value(
				"PM Clearance",
				cl_name,
				{"manager_approver": self.manager, "finance_approver": finance_approver},
				update_modified=False,
			)
		else:
			frappe.db.set_value(
				"PM Clearance", cl_name, {"manager_approver": self.manager}, update_modified=False
			)
		cl = frappe.get_doc("PM Clearance", cl_name)
		if _wf_title(cl.workflow_state) in ("", "Draft"):
			apply_pm_workflow(cl, "PM Submit Finance Review")
		frappe.set_user(self.manager)
		cl = frappe.get_doc("PM Clearance", cl_name)
		if _wf_title(cl.workflow_state) == "Pending Manager Approval":
			apply_pm_workflow(cl, "PM Manager Approve")
		frappe.set_user("Administrator")
		if clear_finance_stamp:
			frappe.db.set_value(
				"PM Clearance", cl_name, {"finance_approver": None}, update_modified=False
			)
		cl = frappe.get_doc("PM Clearance", cl_name)
		self.assertEqual(_wf_title(cl.workflow_state), "Pending Finance Review")

	def _pending_finance_clearance(self, *, clear_finance_stamp: bool = True) -> str:
		"""Funded clearance at Pending Finance Review for role-queue assertions."""
		_prepare_role_queue_scenario()
		emp, req = self._funded_holder()
		cl_name = self._new_clearance_with_pi(emp, req, self._insert_submitted_pi())
		self._advance_to_pending_finance(cl_name, clear_finance_stamp=clear_finance_stamp)
		return cl_name

	def _clearance_visible_to_user(self, user: str, cl_name: str) -> bool:
		frappe.set_user(user)
		try:
			try:
				rows = frappe.get_list("PM Clearance", fields=["name"], limit_page_length=200)
				names = {r["name"] for r in rows}
				if cl_name in names:
					return True
			except frappe.PermissionError:
				pass
			return frappe.has_permission(
				"PM Clearance", "read", doc=frappe.get_doc("PM Clearance", cl_name)
			)
		finally:
			frappe.set_user("Administrator")

	def _allowed_finance_actions(self, user: str, cl_name: str) -> list[str]:
		frappe.set_user(user)
		try:
			from erpnext_extensions.petty_management.services.workflow_utils import (
				get_allowed_workflow_actions,
			)

			doc = frappe.get_doc("PM Clearance", cl_name)
			return [t.get("action") for t in get_allowed_workflow_actions(doc) if t.get("action")]
		finally:
			frappe.set_user("Administrator")

	# --- 1: submit without finance_supervisor when role queue configured ---

	def test_clearance_submit_without_finance_supervisor_when_role_configured(self):
		_prepare_role_queue_scenario()
		emp, req = self._funded_holder()
		pi = self._insert_submitted_pi()
		cl_name = self._new_clearance_with_pi(emp, req, pi)

		settings = frappe.get_single("PM Settings")
		prev_supervisor = getattr(settings, "finance_supervisor", None)
		prev_manager = getattr(settings, "finance_manager", None)
		settings.db_set("finance_supervisor", None, update_modified=False)
		settings.db_set("finance_manager", None, update_modified=False)
		frappe.db.commit()
		try:
			cl = frappe.get_doc("PM Clearance", cl_name)
			apply_pm_workflow(cl, "PM Submit Finance Review")
			cl.reload()
			self.assertIn(
				_wf_title(cl.workflow_state),
				("Pending Manager Approval", "Pending Finance Review"),
				msg="Clearance should submit when role queue replaces named finance supervisor",
			)
		finally:
			settings.db_set("finance_supervisor", prev_supervisor, update_modified=False)
			settings.db_set("finance_manager", prev_manager or self.request_finance, update_modified=False)
			frappe.db.commit()

	# --- 2: settings role resolver ---

	def test_clearance_finance_review_role_resolves_from_settings(self):
		_configure_role_queue_settings(review_role=REVIEWER_ROLE)
		role = _get_clearance_finance_review_role()
		self.assertEqual(role, REVIEWER_ROLE)

	# --- 3–5: queue visibility ---

	def test_reviewer_a_sees_pending_finance_clearance(self):
		cl_name = self._pending_finance_clearance()
		self.assertTrue(
			self._clearance_visible_to_user(self.reviewer_a, cl_name),
			msg="Reviewer A must see Pending Finance Review clearance via role queue",
		)

	def test_reviewer_b_sees_same_pending_finance_clearance(self):
		cl_name = self._pending_finance_clearance()
		self.assertTrue(
			self._clearance_visible_to_user(self.reviewer_b, cl_name),
			msg="Reviewer B must see the same clearance (shared queue)",
		)

	def test_unrelated_petty_user_does_not_see_pending_finance_clearance(self):
		cl_name = self._pending_finance_clearance()
		self.assertFalse(
			self._clearance_visible_to_user(self.unrelated_user, cl_name),
			msg="Unrelated Petty User must not see finance-queue clearance",
		)

	# --- 6–9: finance approve / reject authorization ---

	def test_non_reviewer_cannot_finance_approve_via_workflow(self):
		cl_name = self._pending_finance_clearance()
		actions = self._allowed_finance_actions(self.unrelated_user, cl_name)
		self.assertNotIn(
			"PM Finance Approve",
			actions,
			msg="Non-reviewer must not get Finance Approve workflow action",
		)

	def test_reviewer_a_can_finance_approve(self):
		cl_name = self._pending_finance_clearance()
		actions = self._allowed_finance_actions(self.reviewer_a, cl_name)
		self.assertIn("PM Finance Approve", actions)
		frappe.set_user(self.reviewer_a)
		apply_pm_workflow(frappe.get_doc("PM Clearance", cl_name), "PM Finance Approve")
		frappe.set_user("Administrator")
		cl = frappe.get_doc("PM Clearance", cl_name)
		self.assertEqual(_wf_title(cl.workflow_state), "Approved")

	def test_finance_approver_stamped_after_reviewer_a_approves(self):
		cl_name = self._pending_finance_clearance()
		frappe.db.set_value("PM Clearance", cl_name, {"finance_approver": None}, update_modified=False)
		frappe.set_user(self.reviewer_a)
		apply_pm_workflow(frappe.get_doc("PM Clearance", cl_name), "PM Finance Approve")
		frappe.set_user("Administrator")
		cl = frappe.get_doc("PM Clearance", cl_name)
		self.assertEqual(cl.finance_approver, self.reviewer_a)

	def test_reviewer_b_blocked_after_reviewer_a_approves(self):
		cl_name = self._pending_finance_clearance()
		frappe.set_user(self.reviewer_a)
		apply_pm_workflow(frappe.get_doc("PM Clearance", cl_name), "PM Finance Approve")
		frappe.set_user(self.reviewer_b)
		with self.assertRaises((ValidationError, WorkflowPermissionError)):
			apply_pm_workflow(frappe.get_doc("PM Clearance", cl_name), "PM Finance Approve")
		frappe.set_user("Administrator")

	# --- 10: role removed before action ---

	def test_reviewer_blocked_when_role_removed_before_action(self):
		cl_name = self._pending_finance_clearance()
		self.assertTrue(
			self._clearance_visible_to_user(self.reviewer_a, cl_name),
			msg="Reviewer must see clearance before role removal",
		)
		self.assertIn(
			"PM Finance Approve",
			self._allowed_finance_actions(self.reviewer_a, cl_name),
			msg="Reviewer must have Finance Approve before role removal",
		)

		user = frappe.get_doc("User", self.reviewer_a)
		user.roles = [r for r in user.roles if r.role != REVIEWER_ROLE]
		user.save(ignore_permissions=True)
		frappe.db.commit()
		frappe.clear_cache(user=self.reviewer_a)

		self.assertNotIn("PM Finance Approve", self._allowed_finance_actions(self.reviewer_a, cl_name))
		frappe.set_user(self.reviewer_a)
		with self.assertRaises((ValidationError, WorkflowPermissionError)):
			apply_pm_workflow(frappe.get_doc("PM Clearance", cl_name), "PM Finance Approve")
		frappe.set_user("Administrator")

		cl = frappe.get_doc("PM Clearance", cl_name)
		self.assertEqual(_wf_title(cl.workflow_state), "Pending Finance Review")
		self.assertFalse((cl.finance_approver or "").strip())

		user.reload()
		user.append("roles", {"role": REVIEWER_ROLE})
		user.save(ignore_permissions=True)
		frappe.db.commit()

	# --- 11–12: draft PI guard + workflow action remains open ---

	def test_draft_pi_blocks_reviewer_finance_approve(self):
		_prepare_role_queue_scenario()
		emp, req = self._funded_holder()
		pi = self._insert_draft_pi()
		cl_name = self._new_clearance_with_pi(emp, req, pi)
		self._advance_to_pending_finance(cl_name, clear_finance_stamp=True)
		frappe.set_user(self.reviewer_a)
		with self.assertRaises(ValidationError) as ctx:
			apply_pm_workflow(frappe.get_doc("PM Clearance", cl_name), "PM Finance Approve")
		self.assertIn("not submitted", str(ctx.exception).lower())
		frappe.set_user("Administrator")

	def test_failed_draft_pi_finance_approve_keeps_state_and_open_workflow_action(self):
		_prepare_role_queue_scenario()
		emp, req = self._funded_holder()
		pi = self._insert_draft_pi()
		cl_name = self._new_clearance_with_pi(emp, req, pi)
		self._advance_to_pending_finance(cl_name, clear_finance_stamp=True)
		frappe.set_user(self.reviewer_a)
		with self.assertRaises(ValidationError):
			apply_pm_workflow(frappe.get_doc("PM Clearance", cl_name), "PM Finance Approve")
		frappe.set_user("Administrator")
		cl = frappe.get_doc("PM Clearance", cl_name)
		self.assertEqual(_wf_title(cl.workflow_state), "Pending Finance Review")
		self.assertFalse((cl.finance_approver or "").strip())
		actions = _open_workflow_actions(cl_name)
		self.assertTrue(actions, msg="Open Workflow Action must remain after failed Finance Approve")
		_ensure_role(REVIEWER_ROLE)
		self.assertTrue(
			any(REVIEWER_ROLE in (a.get("permitted_roles") or []) for a in actions),
			msg=f"Workflow Action must permit {REVIEWER_ROLE} (role queue, not named user)",
		)

	# --- 13–14: assignment rules ---

	def test_manager_assignment_rule_still_enabled(self):
		self.assertTrue(frappe.db.exists("Assignment Rule", MANAGER_ASSIGNMENT_RULE))
		rule = frappe.get_doc("Assignment Rule", MANAGER_ASSIGNMENT_RULE)
		self.assertEqual(rule.rule, "Based on Field")
		self.assertFalse(cint(rule.disabled))
		self.assertEqual((rule.field or "").strip(), "manager_approver")

	def test_finance_assignment_rule_disabled_or_absent(self):
		if not frappe.db.exists("Assignment Rule", FINANCE_ASSIGNMENT_RULE):
			return
		rule = frappe.get_doc("Assignment Rule", FINANCE_ASSIGNMENT_RULE)
		self.assertTrue(
			cint(rule.disabled),
			msg="PM Clearance Finance Review Assignment Rule must be disabled for role queue",
		)

	# --- 15: operational visibility regression ---

	def test_operational_pm_visibility_role_still_unrestricted(self):
		self.assertTrue(_is_pm_visibility_unrestricted(self.accountant))
		self.assertEqual(pm_clearance_permission_query_conditions(self.accountant), "")

	# --- 16: PM Request named finance unchanged (regression) ---

	def test_pm_request_finance_still_uses_named_finance_manager_stamp(self):
		emp = tpm._make_employee()
		frappe.db.set_value("Employee", emp, "expense_approver", self.manager, update_modified=False)
		tpm._make_holder(emp)
		req = frappe.new_doc("PM Request")
		req.company = tpm.COMPANY
		req.employee = emp
		req.transaction_date = today()
		req.append("details", {"advance_amount": 1_000})
		req.insert(ignore_permissions=True)
		apply_pm_workflow(req, "PM Submit for Approval")
		req.reload()
		self.assertEqual(req.finance_approver, self.request_finance)
		# PM Request finance remains named-user (not role queue)
		wf_name = frappe.db.get_value("Workflow", {"document_type": "PM Request", "is_active": 1}, "name")
		self.assertTrue(wf_name)
		for row in frappe.get_all(
			"Workflow Transition",
			filters={"parent": wf_name, "action": "PM Finance Approve"},
			fields=["condition"],
		):
			cond = (row.get("condition") or "").strip()
			if cond:
				self.assertIn("finance_approver", cond)
				self.assertIn("session.user", cond)
		self._track("PM Request", req.name)
		self._track("Employee", emp)

	# --- 17: concurrent reviewers — exactly one success ---

	def test_concurrent_reviewers_only_one_finance_approve_succeeds(self):
		cl_name = self._pending_finance_clearance()

		frappe.set_user(self.reviewer_a)
		apply_pm_workflow(frappe.get_doc("PM Clearance", cl_name), "PM Finance Approve")
		frappe.db.commit()

		frappe.set_user(self.reviewer_b)
		with self.assertRaises((ValidationError, WorkflowPermissionError)):
			apply_pm_workflow(frappe.get_doc("PM Clearance", cl_name), "PM Finance Approve")
		frappe.set_user("Administrator")

		cl = frappe.get_doc("PM Clearance", cl_name)
		self.assertEqual(_wf_title(cl.workflow_state), "Approved")
		self.assertEqual(cl.finance_approver, self.reviewer_a)
