"""Backend E2E smoke: PM Request + PM Clearance lifecycles (workflow via apply_workflow)."""

from __future__ import annotations

import json

import frappe
from frappe.utils import flt, today

import erpnext_extensions.petty_management.tests.test_pm_clearance as pm_ct
from erpnext_extensions.patches.post_model_sync.add_petty_management_workflows import (
	repair_pm_clearance_workflow,
	repair_pm_request_workflow,
)
from erpnext_extensions.petty_management.services.opening_advance_service import (
	get_opening_advance_available_amount,
)
from erpnext_extensions.petty_management.services.workflow_utils import (
	apply_pm_workflow,
	resolve_workflow_state_link,
)
from erpnext_extensions.petty_management.smoke.final_acceptance_opening_clearance import (
	_patch_pi_round_floats_compat,
)


def _submit_pi(pi):
	bs = frappe.get_single("Buying Settings")
	prev = bs.po_required
	bs.po_required = 0
	bs.save(ignore_permissions=True)
	frappe.db.commit()
	try:
		pi.insert(ignore_permissions=True)
		pi.submit()
	finally:
		bs.po_required = prev
		bs.save(ignore_permissions=True)
		frappe.db.commit()


def execute():
	frappe.set_user("Administrator")
	_patch_pi_round_floats_compat()
	repair_pm_request_workflow()
	repair_pm_clearance_workflow()
	frappe.db.commit()
	pm_ct._ensure_company_context()
	pm_ct._ensure_petty_account()
	report = {"steps": []}

	def step(name, ok, **extra):
		report["steps"].append({"step": name, "ok": ok, **extra})

	try:
		emp = pm_ct._make_employee()
		holder = pm_ct._make_holder(emp)
		req = frappe.new_doc("PM Request")
		req.company = pm_ct.COMPANY
		req.employee = emp
		req.transaction_date = today()
		req.append("details", {"advance_amount": 3000})
		req.insert(ignore_permissions=True)
		frappe.db.set_value(
			"PM Request",
			req.name,
			"workflow_state",
			resolve_workflow_state_link("Draft"),
			update_modified=False,
		)
		req.reload()
		apply_pm_workflow(req, "PM Submit for Approval")
		apply_pm_workflow(req, "PM Approve")
		req.reload()
		step("pm_request_workflow", True, workflow_state=req.workflow_state, status=req.status)
		if not pm_ct.BANK_ACCOUNT:
			raise frappe.ValidationError("No bank account")
		from erpnext_extensions.petty_management.services.request_service import create_payment_entry

		pe_name = create_payment_entry(req.name)
		pe = frappe.get_doc("Payment Entry", pe_name)
		if pe.docstatus == 0:
			pe.submit()
		req.reload()
		step(
			"pm_request_pe",
			req.payment_status == "Paid",
			payment_entry=pe_name,
			party_type=pe.party_type,
			party=pe.party,
		)

		pi = pm_ct._make_pi_outstanding(1500)
		_submit_pi(pi)
		cl = frappe.new_doc("PM Clearance")
		cl.company = pm_ct.COMPANY
		cl.employee = emp
		cl.transaction_date = today()
		pm_ct._append_pm_clearance_detail_row(
			cl,
			{"settlement_type": "Purchase Invoice", "purchase_invoice": pi.name, "allocated_amount": 1500},
		)
		cl.append("request_allocations", {"pm_request": req.name, "allocated_amount": 1500})
		cl.insert(ignore_permissions=True)
		frappe.db.set_value(
			"PM Clearance",
			cl.name,
			"workflow_state",
			resolve_workflow_state_link("Draft"),
			update_modified=False,
		)
		cl.reload()
		apply_pm_workflow(cl, "PM Submit Finance Review")
		apply_pm_workflow(cl, "PM Approve")
		from erpnext_extensions.petty_management.services import journal_entry_service as jes

		out = jes.settle_petty_cash(cl.name)
		je = frappe.get_doc("Journal Entry", out["journal_entry"])
		if je.docstatus == 0:
			je.submit()
		cr = [a for a in je.accounts if flt(a.credit_in_account_currency) > 0][0]
		step(
			"pm_clearance_request_path",
			cr.party_type == "Employee" and cr.party == emp,
			je=je.name,
			credit_party_type=cr.party_type,
		)

		oa = frappe.new_doc("PM Opening Advance")
		oa.holder = holder
		oa.opening_date = today()
		oa.opening_source_type = "Opening Balance"
		oa.opening_advance_amount = 5000
		oa.reference_no = "E2E-OA"
		oa.insert(ignore_permissions=True)
		oa.submit()
		bal0 = get_opening_advance_available_amount(oa.name)
		pi2 = pm_ct._make_pi_outstanding(1000)
		_submit_pi(pi2)
		cl2 = frappe.new_doc("PM Clearance")
		cl2.company = pm_ct.COMPANY
		cl2.employee = emp
		cl2.transaction_date = today()
		pm_ct._append_pm_clearance_detail_row(
			cl2,
			{"settlement_type": "Purchase Invoice", "purchase_invoice": pi2.name, "allocated_amount": 1000},
		)
		cl2.append(
			"request_allocations",
			{
				"funding_source_type": "PM Opening Advance",
				"pm_opening_advance": oa.name,
				"allocated_amount": 1000,
			},
		)
		cl2.insert(ignore_permissions=True)
		frappe.db.set_value(
			"PM Clearance",
			cl2.name,
			"workflow_state",
			resolve_workflow_state_link("Draft"),
			update_modified=False,
		)
		cl2.reload()
		apply_pm_workflow(cl2, "PM Submit Finance Review")
		apply_pm_workflow(cl2, "PM Approve")
		out2 = jes.settle_petty_cash(cl2.name)
		je2 = frappe.get_doc("Journal Entry", out2["journal_entry"])
		if je2.docstatus == 0:
			je2.submit()
		bal1 = get_opening_advance_available_amount(oa.name)
		je2.cancel()
		cl2.reload()
		cl2.cancel()
		bal2 = get_opening_advance_available_amount(oa.name)
		step(
			"pm_clearance_opening_path",
			abs(bal0 - bal2) < 0.01,
			opening_before=bal0,
			opening_after_je=bal1,
			opening_after_cancel=bal2,
		)
		report["status"] = "OK"
	except Exception as exc:
		report["status"] = "FAILED"
		report["error"] = str(exc)
		step("failure", False, error=str(exc))
	print(json.dumps(report, indent=2, default=str))
