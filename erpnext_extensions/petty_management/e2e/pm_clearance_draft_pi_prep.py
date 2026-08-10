# Copyright (c) 2026, ERPNext Extensions contributors
"""Prep Draft PI Clearance at Pending Finance Review for Playwright (v4.1.5)."""

from __future__ import annotations

import frappe
from frappe.utils import cint, flt, today
from frappe.utils.password import update_password

from erpnext_extensions.e2e.e2e_fixture import e2e_run_context
from erpnext_extensions.petty_management.services.workflow_utils import apply_pm_workflow
from erpnext_extensions.petty_management.tests import test_pm_clearance as tpm

HOLDER = "pm_draft_pi_holder_e2e@example.com"
MANAGER = "pm_draft_pi_mgr_e2e@example.com"
FINANCE = "pm_draft_pi_fin_e2e@example.com"
PASSWORD = "pm_sec_test_1"


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


def _wf_title(link: str | None) -> str:
	if not link:
		return ""
	return (frappe.db.get_value("Workflow State", link, "workflow_state_name") or link or "").strip()


@frappe.whitelist()
def prepare() -> dict:
	frappe.set_user("Administrator")
	tpm._ensure_company_context()
	if not tpm.COMPANY:
		frappe.throw("No Company")

	desk = ["Accounts User", "Employee", "System Manager"]
	_ensure_user(HOLDER, ["Petty Management User", *desk])
	_ensure_user(MANAGER, ["Petty Management User", "Expense Approver", *desk])
	_ensure_user(FINANCE, ["Petty Management Accountant", *desk])

	settings = frappe.get_single("PM Settings")
	settings.db_set("finance_manager", FINANCE, update_modified=False)
	settings.db_set("finance_supervisor", FINANCE, update_modified=False)
	settings.db_set("require_named_manager_approver", 1, update_modified=False)

	emp = tpm._make_employee()
	frappe.db.set_value("Employee", emp, "expense_approver", MANAGER, update_modified=False)
	frappe.db.set_value("Employee", emp, "user_id", HOLDER, update_modified=False)
	tpm._make_holder(emp)
	req, pe = tpm._fund_pm_request(emp, 80_000.0)
	from erpnext_extensions.petty_management.services.workflow_utils import resolve_workflow_state_link

	fa = resolve_workflow_state_link("Finance Approved")
	frappe.db.set_value(
		"PM Request",
		req,
		{"workflow_state": fa, "status": "Paid", "payment_status": "Paid"},
		update_modified=False,
	)

	pi = tpm._make_pi_outstanding(9_000)
	sup = pi.supplier
	sname = f"PM Draft PI E2E {frappe.generate_hash(length=5)}"
	frappe.db.set_value("Supplier", sup, "supplier_name", sname, update_modified=False)
	pi.insert(ignore_permissions=True)
	alloc = flt(pi.grand_total or 9000)

	cl = frappe.new_doc("PM Clearance")
	cl.company = tpm.COMPANY
	cl.employee = emp
	cl.posting_date = today()
	cl.transaction_date = today()
	tpm._append_pm_clearance_detail_row(
		cl,
		{
			"settlement_type": "Purchase Invoice",
			"purchase_invoice": pi.name,
			"allocated_amount": alloc,
		},
	)
	cl.append(
		"request_allocations",
		{"funding_source_type": "PM Request", "pm_request": req, "allocated_amount": alloc},
	)
	cl.insert(ignore_permissions=True)
	frappe.db.set_value(
		"PM Clearance",
		cl.name,
		{"manager_approver": MANAGER, "finance_approver": FINANCE},
		update_modified=False,
	)
	apply_pm_workflow(frappe.get_doc("PM Clearance", cl.name), "PM Submit Finance Review")
	frappe.set_user(MANAGER)
	apply_pm_workflow(frappe.get_doc("PM Clearance", cl.name), "PM Manager Approve")
	frappe.set_user("Administrator")
	cl = frappe.get_doc("PM Clearance", cl.name)
	frappe.db.commit()

	ctx = e2e_run_context()
	return {
		**ctx,
		"company": tpm.COMPANY,
		"employee": emp,
		"pm_request": req,
		"payment_entry": pe,
		"draft_pi": pi.name,
		"pm_clearance": cl.name,
		"workflow_state": cl.workflow_state,
		"workflow_state_title": _wf_title(cl.workflow_state),
		"status": cl.status,
		"supplier": sup,
		"supplier_name": sname,
		"pi_grand_total": float(alloc),
		"users": {
			"holder": {"email": HOLDER, "password": PASSWORD},
			"manager": {"email": MANAGER, "password": PASSWORD},
			"finance": {"email": FINANCE, "password": PASSWORD},
		},
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
def count_open_finance_todos(pm_clearance: str) -> dict:
	frappe.set_user("Administrator")
	rows = frappe.get_all(
		"ToDo",
		filters={
			"reference_type": "PM Clearance",
			"reference_name": pm_clearance,
			"status": "Open",
		},
		fields=["name", "allocated_to"],
	)
	return {"open_count": len(rows), "todos": rows}


@frappe.whitelist()
def je_references_pi(journal_entry: str, purchase_invoice: str) -> dict:
	frappe.set_user("Administrator")
	refs = frappe.get_all(
		"Journal Entry Account",
		filters={"parent": journal_entry, "reference_type": "Purchase Invoice", "reference_name": purchase_invoice},
		pluck="name",
	)
	pi_ds = cint(frappe.db.get_value("Purchase Invoice", purchase_invoice, "docstatus"))
	return {"ok": bool(refs) and pi_ds == 1, "account_rows": len(refs), "pi_docstatus": pi_ds}
