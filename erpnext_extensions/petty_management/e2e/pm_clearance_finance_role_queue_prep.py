# Copyright (c) 2026, ERPNext Extensions contributors
"""Prep fixtures for PM Clearance Finance Review Role Queue Playwright (v4.5.3)."""

from __future__ import annotations

import concurrent.futures

import frappe
from frappe.exceptions import ValidationError
from frappe.model.workflow import WorkflowPermissionError
from frappe.utils import cint, flt, today
from frappe.utils.password import update_password

from erpnext_extensions.e2e.e2e_fixture import e2e_run_context
from erpnext_extensions.petty_management.services.clearance_finance_review import (
	DEFAULT_CLEARANCE_FINANCE_REVIEW_ROLE,
	get_clearance_finance_review_role,
)
from erpnext_extensions.petty_management.services.workflow_utils import (
	apply_pm_workflow,
	resolve_workflow_state_link,
)
from erpnext_extensions.petty_management.tests import test_pm_clearance as tpm

PASSWORD = "pm_sec_test_1"
HOLDER = "pm_clr_rq_holder_e2e@example.com"
MANAGER = "pm_clr_rq_mgr_e2e@example.com"
REVIEWER_A = "pm_clr_rq_rev_a_e2e@example.com"
REVIEWER_B = "pm_clr_rq_rev_b_e2e@example.com"
UNRELATED = "pm_clr_rq_unrelated_e2e@example.com"
REQUEST_FINANCE = "pm_clr_rq_req_fin_e2e@example.com"


def _wf_title(link: str | None) -> str:
	if not link:
		return ""
	return (frappe.db.get_value("Workflow State", link, "workflow_state_name") or link or "").strip()


def _ensure_user(email: str, roles: list[str]) -> str:
	if not frappe.db.exists("User", email):
		u = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": email.split("@")[0][:30],
				"send_welcome_email": 0,
				"user_type": "System User",
				"enabled": 1,
			}
		)
		u.insert(ignore_permissions=True)
	else:
		u = frappe.get_doc("User", email)
	u.roles = []
	for role in roles:
		if not frappe.db.exists("Role", role):
			frappe.get_doc({"doctype": "Role", "role_name": role}).insert(ignore_permissions=True)
		u.append("roles", {"role": role})
	u.enabled = 1
	u.save(ignore_permissions=True)
	update_password(email, PASSWORD)
	frappe.db.commit()
	return email


def _ensure_role_queue_site() -> str:
	from erpnext_extensions.patches.post_model_sync.migrate_pm_clearance_finance_role_queue_v453 import (
		execute as migrate_v453,
	)

	migrate_v453()
	review_role = DEFAULT_CLEARANCE_FINANCE_REVIEW_ROLE
	if not frappe.db.exists("Role", review_role):
		frappe.get_doc({"doctype": "Role", "role_name": review_role}).insert(ignore_permissions=True)
	settings = frappe.get_single("PM Settings")
	settings.db_set("clearance_finance_review_role", review_role, update_modified=False)
	settings.db_set("require_named_manager_approver", 1, update_modified=False)
	settings.db_set("finance_manager", REQUEST_FINANCE, update_modified=False)
	settings.db_set("ceo_approver", "Administrator", update_modified=False)
	frappe.db.commit()
	return review_role


def _desk_roles() -> list[str]:
	# Desk login needs Accounts User; avoid System Manager / operational visibility.
	return ["Accounts User", "Employee"]


def _ensure_actors(review_role: str) -> dict:
	holder = _ensure_user(HOLDER, ["Petty Management User", *_desk_roles()])
	manager = _ensure_user(
		MANAGER, ["Petty Management User", "Expense Approver", *_desk_roles()]
	)
	reviewer_a = _ensure_user(REVIEWER_A, [review_role, *_desk_roles()])
	reviewer_b = _ensure_user(REVIEWER_B, [review_role, *_desk_roles()])
	unrelated = _ensure_user(UNRELATED, ["Petty Management User", *_desk_roles()])
	_ensure_user(REQUEST_FINANCE, ["Petty Management Accountant", *_desk_roles(), "System Manager"])
	return {
		"holder": {"email": holder, "password": PASSWORD},
		"manager": {"email": manager, "password": PASSWORD},
		"reviewer_a": {"email": reviewer_a, "password": PASSWORD},
		"reviewer_b": {"email": reviewer_b, "password": PASSWORD},
		"unrelated": {"email": unrelated, "password": PASSWORD},
		"request_finance": {"email": REQUEST_FINANCE, "password": PASSWORD},
	}


def _funded_holder(manager: str, holder: str, amount: float = 100_000.0) -> tuple[str, str, str]:
	emp = tpm._make_employee()
	frappe.db.set_value("Employee", emp, "expense_approver", manager, update_modified=False)
	frappe.db.set_value("Employee", emp, "user_id", holder, update_modified=False)
	tpm._make_holder(emp)
	req, pe = tpm._fund_pm_request(emp, amount)
	fa = resolve_workflow_state_link("Finance Approved")
	frappe.db.set_value(
		"PM Request",
		req,
		{"workflow_state": fa, "status": "Paid", "payment_status": "Paid"},
		update_modified=False,
	)
	frappe.db.commit()
	return emp, req, pe


def _new_clearance(emp: str, req: str, pi_name: str, allocated: float | None = None) -> str:
	pi = frappe.get_doc("Purchase Invoice", pi_name)
	alloc = flt(allocated)
	if alloc <= 0:
		alloc = flt(pi.outstanding_amount if cint(pi.docstatus) == 1 else (pi.grand_total or 0))
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
	frappe.db.commit()
	return cl.name


def _advance_to_pending_finance(cl_name: str, manager: str) -> None:
	frappe.db.set_value(
		"PM Clearance",
		cl_name,
		{"manager_approver": manager, "finance_approver": None},
		update_modified=False,
	)
	cl = frappe.get_doc("PM Clearance", cl_name)
	if _wf_title(cl.workflow_state) in ("", "Draft"):
		apply_pm_workflow(cl, "PM Submit Finance Review")
	frappe.set_user(manager)
	cl = frappe.get_doc("PM Clearance", cl_name)
	if _wf_title(cl.workflow_state) == "Pending Manager Approval":
		apply_pm_workflow(cl, "PM Manager Approve")
	frappe.set_user("Administrator")
	cl = frappe.get_doc("PM Clearance", cl_name)
	if _wf_title(cl.workflow_state) != "Pending Finance Review":
		frappe.throw(f"Expected Pending Finance Review, got {_wf_title(cl.workflow_state)}")
	frappe.db.commit()


@frappe.whitelist()
def snapshot_workflow_actions(pm_clearance: str) -> dict:
	"""DB snapshot of Workflow Action rows for a Clearance."""
	frappe.set_user("Administrator")
	actions = frappe.get_all(
		"Workflow Action",
		filters={"reference_doctype": "PM Clearance", "reference_name": pm_clearance},
		fields=["name", "status", "user", "completed_by", "workflow_state", "creation", "modified"],
		order_by="creation asc",
	)
	for row in actions:
		row["permitted_roles"] = frappe.get_all(
			"Workflow Action Permitted Role",
			filters={"parent": row["name"]},
			pluck="role",
		)
		row["workflow_state_title"] = _wf_title(row.get("workflow_state"))
	open_actions = [a for a in actions if a.get("status") == "Open"]
	completed = [a for a in actions if a.get("status") == "Completed"]
	return {
		"all": actions,
		"open": open_actions,
		"completed": completed,
		"open_count": len(open_actions),
		"completed_count": len(completed),
	}


@frappe.whitelist()
def finance_email_disabled() -> dict:
	"""Confirm Pending Finance Review send_email is off on active Clearance workflow."""
	frappe.set_user("Administrator")
	wf_name = frappe.db.get_value("Workflow", {"document_type": "PM Clearance", "is_active": 1}, "name")
	if not wf_name:
		return {"ok": False, "error": "No active PM Clearance Workflow"}
	w = frappe.get_doc("Workflow", wf_name)
	pending = resolve_workflow_state_link("Pending Finance Review")
	row = next((s for s in w.states if s.state == pending), None)
	send_email = cint(getattr(row, "send_email", 1)) if row else None
	return {
		"ok": send_email == 0 and cint(w.send_email_alert) == 0,
		"workflow": wf_name,
		"send_email_alert": cint(w.send_email_alert),
		"pending_finance_send_email": send_email,
		"review_role": get_clearance_finance_review_role(),
	}


@frappe.whitelist()
def clearance_visible_to(user: str, pm_clearance: str) -> dict:
	frappe.set_user(user)
	try:
		visible_list = False
		try:
			names = {
				r.name
				for r in frappe.get_list("PM Clearance", fields=["name"], limit_page_length=500)
			}
			visible_list = pm_clearance in names
		except frappe.PermissionError:
			visible_list = False
		can_read = False
		try:
			can_read = bool(
				frappe.has_permission("PM Clearance", "read", doc=frappe.get_doc("PM Clearance", pm_clearance))
			)
		except Exception:
			can_read = False
		return {"user": user, "visible_list": visible_list, "can_read": can_read, "visible": visible_list or can_read}
	finally:
		frappe.set_user("Administrator")


@frappe.whitelist()
def allowed_finance_actions(user: str, pm_clearance: str) -> dict:
	from erpnext_extensions.petty_management.services.workflow_utils import get_allowed_workflow_actions

	frappe.set_user(user)
	try:
		doc = frappe.get_doc("PM Clearance", pm_clearance)
		actions = sorted({t.get("action") for t in get_allowed_workflow_actions(doc) if t.get("action")})
		return {"user": user, "actions": actions}
	finally:
		frappe.set_user("Administrator")


@frappe.whitelist()
def try_finance_approve(user: str, pm_clearance: str) -> dict:
	"""Attempt Finance Approve as ``user``; return ok/error without raising to caller."""
	frappe.set_user(user)
	try:
		apply_pm_workflow(frappe.get_doc("PM Clearance", pm_clearance), "PM Finance Approve")
		frappe.db.commit()
		return {"user": user, "ok": True}
	except Exception as e:
		frappe.db.rollback()
		return {"user": user, "ok": False, "error": str(e)}
	finally:
		frappe.set_user("Administrator")


@frappe.whitelist()
def get_clearance_state(pm_clearance: str) -> dict:
	frappe.set_user("Administrator")
	cl = frappe.get_doc("PM Clearance", pm_clearance)
	return {
		"name": cl.name,
		"workflow_state": cl.workflow_state,
		"workflow_state_title": _wf_title(cl.workflow_state),
		"status": cl.status,
		"finance_approver": cl.finance_approver,
		"manager_approver": cl.manager_approver,
		"docstatus": cint(cl.docstatus),
	}


@frappe.whitelist()
def prepare_happy_path() -> dict:
	"""Draft Clearance ready for Holder submit → Manager → dual Reviewer queue."""
	frappe.set_user("Administrator")
	tpm._ensure_company_context()
	if not tpm.COMPANY:
		frappe.throw("No Company")

	review_role = _ensure_role_queue_site()
	users = _ensure_actors(review_role)
	emp, req, pe = _funded_holder(users["manager"]["email"], users["holder"]["email"])

	pi = tpm._make_pi_outstanding(8_500)
	pi.insert(ignore_permissions=True)
	pi.submit()
	cl_name = _new_clearance(emp, req, pi.name, 8_500)
	# Stamp manager for Assignment Rule / manager path; leave finance blank.
	frappe.db.set_value(
		"PM Clearance",
		cl_name,
		{"manager_approver": users["manager"]["email"], "finance_approver": None},
		update_modified=False,
	)
	frappe.db.commit()
	cl = frappe.get_doc("PM Clearance", cl_name)

	return {
		**e2e_run_context(),
		"scenario": "happy_path",
		"company": tpm.COMPANY,
		"employee": emp,
		"pm_request": req,
		"payment_entry": pe,
		"purchase_invoice": pi.name,
		"pm_clearance": cl_name,
		"workflow_state_title": _wf_title(cl.workflow_state),
		"status": cl.status,
		"finance_approver": cl.finance_approver,
		"review_role": review_role,
		"users": users,
		"email": finance_email_disabled(),
	}


@frappe.whitelist()
def prepare_draft_pi_branch() -> dict:
	"""Clearance with Draft PI already at Pending Finance Review."""
	frappe.set_user("Administrator")
	tpm._ensure_company_context()
	if not tpm.COMPANY:
		frappe.throw("No Company")

	review_role = _ensure_role_queue_site()
	users = _ensure_actors(review_role)
	emp, req, pe = _funded_holder(users["manager"]["email"], users["holder"]["email"], 80_000)

	pi = tpm._make_pi_outstanding(9_000)
	pi.insert(ignore_permissions=True)
	alloc = flt(pi.grand_total or 9000)
	cl_name = _new_clearance(emp, req, pi.name, alloc)
	_advance_to_pending_finance(cl_name, users["manager"]["email"])
	cl = frappe.get_doc("PM Clearance", cl_name)
	wa = snapshot_workflow_actions(cl_name)

	return {
		**e2e_run_context(),
		"scenario": "draft_pi",
		"company": tpm.COMPANY,
		"employee": emp,
		"pm_request": req,
		"payment_entry": pe,
		"draft_pi": pi.name,
		"pm_clearance": cl_name,
		"workflow_state_title": _wf_title(cl.workflow_state),
		"status": cl.status,
		"finance_approver": cl.finance_approver,
		"review_role": review_role,
		"users": users,
		"workflow_actions": wa,
		"email": finance_email_disabled(),
	}


@frappe.whitelist()
def prepare_concurrency() -> dict:
	"""Submitted PI Clearance at Pending Finance Review for parallel approve race."""
	frappe.set_user("Administrator")
	tpm._ensure_company_context()
	if not tpm.COMPANY:
		frappe.throw("No Company")

	review_role = _ensure_role_queue_site()
	users = _ensure_actors(review_role)
	emp, req, pe = _funded_holder(users["manager"]["email"], users["holder"]["email"])

	pi = tpm._make_pi_outstanding(7_700)
	pi.insert(ignore_permissions=True)
	pi.submit()
	cl_name = _new_clearance(emp, req, pi.name, 7_700)
	_advance_to_pending_finance(cl_name, users["manager"]["email"])
	cl = frappe.get_doc("PM Clearance", cl_name)

	return {
		**e2e_run_context(),
		"scenario": "concurrency",
		"company": tpm.COMPANY,
		"employee": emp,
		"pm_request": req,
		"payment_entry": pe,
		"purchase_invoice": pi.name,
		"pm_clearance": cl_name,
		"workflow_state_title": _wf_title(cl.workflow_state),
		"status": cl.status,
		"finance_approver": cl.finance_approver,
		"review_role": review_role,
		"users": users,
		"workflow_actions": snapshot_workflow_actions(cl_name),
	}


@frappe.whitelist()
def submit_prepared_pi(purchase_invoice: str) -> dict:
	frappe.set_user("Administrator")
	pi = frappe.get_doc("Purchase Invoice", purchase_invoice)
	if cint(pi.docstatus) == 0:
		pi.submit()
		frappe.db.commit()
	return {
		"name": pi.name,
		"docstatus": int(pi.docstatus),
		"outstanding_amount": float(pi.outstanding_amount or 0),
	}


@frappe.whitelist()
def refresh_clearance_pi_amounts(pm_clearance: str, purchase_invoice: str) -> dict:
	"""After PI submit, sync outstanding onto clearance detail rows."""
	frappe.set_user("Administrator")
	pi = frappe.get_doc("Purchase Invoice", purchase_invoice)
	cl = frappe.get_doc("PM Clearance", pm_clearance)
	for row in cl.details:
		if row.purchase_invoice == purchase_invoice:
			row.outstanding_amount = flt(pi.outstanding_amount)
			if flt(row.allocated_amount) > flt(pi.outstanding_amount):
				row.allocated_amount = flt(pi.outstanding_amount)
	cl.save(ignore_permissions=True)
	frappe.db.commit()
	return {"ok": True, "outstanding_amount": float(pi.outstanding_amount or 0)}


def _try_finance_approve(user: str, pm_clearance: str) -> dict:
	"""Run in a fresh DB connection context for parallel race."""
	frappe.connect(site=frappe.local.site)
	frappe.set_user(user)
	try:
		apply_pm_workflow(frappe.get_doc("PM Clearance", pm_clearance), "PM Finance Approve")
		frappe.db.commit()
		return {"user": user, "ok": True}
	except (ValidationError, WorkflowPermissionError, frappe.PermissionError) as e:
		frappe.db.rollback()
		return {"user": user, "ok": False, "error": str(e)}
	except Exception as e:
		frappe.db.rollback()
		return {"user": user, "ok": False, "error": str(e)}
	finally:
		frappe.set_user("Administrator")


@frappe.whitelist()
def parallel_finance_approve(pm_clearance: str, user_a: str, user_b: str) -> dict:
	"""True parallel Finance Approve attempts — exactly one must succeed."""
	frappe.set_user("Administrator")
	site = frappe.local.site

	def _worker(user: str) -> dict:
		import frappe as _frappe

		_frappe.init(site=site)
		_frappe.connect()
		try:
			_frappe.set_user(user)
			try:
				apply_pm_workflow(_frappe.get_doc("PM Clearance", pm_clearance), "PM Finance Approve")
				_frappe.db.commit()
				return {"user": user, "ok": True}
			except Exception as e:
				_frappe.db.rollback()
				return {"user": user, "ok": False, "error": str(e)}
		finally:
			_frappe.destroy()

	with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
		futs = [pool.submit(_worker, user_a), pool.submit(_worker, user_b)]
		results = [f.result() for f in concurrent.futures.as_completed(futs)]

	frappe.connect()
	frappe.set_user("Administrator")
	state = get_clearance_state(pm_clearance)
	wa = snapshot_workflow_actions(pm_clearance)
	successes = [r for r in results if r.get("ok")]
	return {
		"results": results,
		"success_count": len(successes),
		"state": state,
		"workflow_actions": wa,
		"ok": len(successes) == 1
		and state.get("workflow_state_title") == "Approved"
		and state.get("finance_approver") in (user_a, user_b)
		and wa.get("open_count", 0) == 0,
	}
