# Copyright (c) 2026, Farbod Siyahpoosh and contributors
# For license information, please see license.txt

"""Lightweight verification flow (no ERPNext test_account / test_payment_entry imports).

Run::

	bench --site <site> execute erpnext_extensions.petty_management.tests.pm_verification_smoke.run_pm_verification_smoke

Returns a dict of step names and outcomes (document names, amounts, errors).
"""

from __future__ import annotations

import unittest
from typing import Any

import frappe
from frappe.exceptions import ValidationError
from frappe.utils import flt, today

from erpnext_extensions.petty_management.tests import test_pm_clearance as tpm


def run_pm_verification_smoke() -> dict[str, Any]:
	frappe.set_user("Administrator")
	out: dict[str, Any] = {"steps": [], "pass": True}
	tpm._ensure_company_context()
	if not tpm.COMPANY:
		out["pass"] = False
		out["error"] = "No Company"
		return out
	if not tpm.BANK_ACCOUNT:
		out["pass"] = False
		out["error"] = f"No bank/cash for company {tpm.COMPANY!r}"
		return out

	def step(step_id: str, **payload: Any) -> None:
		out["steps"].append({"step": step_id, **payload})

	try:
		tpm._ensure_petty_account()
		emp = tpm._make_employee()
		step("employee", employee=emp)
		holder_name = tpm._make_holder(emp)
		step("pm_holder", holder=holder_name)

		from erpnext_extensions.petty_management.doctype.pm_clearance import pm_clearance as mod
		from erpnext_extensions.petty_management.services.allocation_service import (
			get_pm_request_available_amount,
			sum_prior_pm_request_allocations,
		)
		from erpnext_extensions.petty_management.services.request_service import (
			create_payment_entry,
			request_ready_for_payment_entry,
		)

		req = frappe.new_doc("PM Request")
		req.company = tpm.COMPANY
		req.employee = emp
		req.transaction_date = today()
		req.append("details", {"advance_amount": 8_000})
		req.insert()
		req.submit()
		req = frappe.get_doc("PM Request", req.name)
		step("pm_request_submitted", pm_request=req.name, amount=8_000)

		ok_before, reason_before = request_ready_for_payment_entry(req)
		step("create_pe_before_approve", ready=ok_before, reason=str(reason_before or ""))
		if ok_before:
			out["pass"] = False
			step("FAIL_expected_create_pe_blocked_before_approved")
			return out

		appr = tpm._workflow_state_for("PM Request", "Finance Approved")
		if not appr:
			out["pass"] = False
			step("FAIL_no_pm_request_waiting_for_payment_workflow_state")
			return out
		tpm._finance_clear_pm_request(req.name)
		req = frappe.get_doc("PM Request", req.name)
		ok_after, reason_after = request_ready_for_payment_entry(req)
		if not ok_after:
			out["pass"] = False
			step("FAIL_create_pe_not_ready_after_approve", reason=str(reason_after or ""))
			return out

		pe1 = create_payment_entry(req.name)
		step("payment_entry_1", payment_entry=pe1)

		try:
			create_payment_entry(req.name)
			out["pass"] = False
			step("FAIL_duplicate_pe_should_have_raised")
		except ValidationError:
			step("duplicate_pe_rejected", ok=True)

		pe_doc = frappe.get_doc("Payment Entry", pe1)
		if pe_doc.docstatus == 1:
			pe_doc.cancel()
		frappe.delete_doc("Payment Entry", pe1, force=True, ignore_permissions=True)
		frappe.db.set_value(
			"PM Request",
			req.name,
			{"payment_entry": None, "payment_status": "Not Paid", "status": "Waiting for Payment"},
			update_modified=False,
		)
		req = frappe.get_doc("PM Request", req.name)

		pe2 = create_payment_entry(req.name)
		pe2_doc = frappe.get_doc("Payment Entry", pe2)
		pe2_doc.submit()
		frappe.db.set_value(
			"PM Request",
			req.name,
			{"payment_entry": pe2, "payment_status": "Paid", "status": "Paid"},
			update_modified=False,
		)
		req = frappe.get_doc("PM Request", req.name)
		step("payment_entry_after_cancel_recreate", payment_entry=pe2)

		pi = tpm._make_pi_outstanding(3_000)
		pi.insert()
		pi.submit()
		step("purchase_invoice", purchase_invoice=pi.name)

		cl = frappe.new_doc("PM Clearance")
		cl.company = tpm.COMPANY
		cl.employee = emp
		cl.transaction_date = today()
		cl.append(
			"details",
			{
				"settlement_type": "Purchase Invoice",
				"purchase_invoice": pi.name,
				"allocated_amount": 3_000,
				**tpm._pm_clearance_detail_policy_fields(),
			},
		)
		cl.append("request_allocations", {"pm_request": req.name, "allocated_amount": 3_000})
		cl.insert()
		step("pm_clearance_draft", pm_clearance=cl.name)
		res_draft = flt(sum_prior_pm_request_allocations(req.name, None))
		step("sum_prior_while_clearance_draft", sum_prior=res_draft)

		cl.submit()
		cl = frappe.get_doc("PM Clearance", cl.name)
		step("pm_clearance_submitted", pm_clearance=cl.name, docstatus=cl.docstatus, status=cl.status)
		res_pending = flt(sum_prior_pm_request_allocations(req.name, None))
		step("sum_prior_after_submit_before_clearance_approve", sum_prior=res_pending)

		tpm._approve_pm_clearance_for_reservation(cl.name)
		res_appr = flt(sum_prior_pm_request_allocations(req.name, None))
		step(
			"sum_prior_after_clearance_approved",
			sum_prior=res_appr,
			available=flt(get_pm_request_available_amount(req.name)),
		)

		prev = frappe.db.count("Journal Entry")
		mod.preview_pm_clearance_settlement(pm_clearance=cl.name)
		step(
			"preview_ok",
			journal_entry_count_before=prev,
			journal_entry_count_after=frappe.db.count("Journal Entry"),
		)

		cl_appr = tpm._workflow_state_for("PM Clearance", "Approved")
		if cl_appr:
			frappe.db.set_value("PM Clearance", cl.name, "workflow_state", cl_appr, update_modified=False)
		s1 = mod.settle_petty_cash(cl.name)
		step("settle_1", **s1)
		s2 = mod.settle_petty_cash(cl.name)
		step("settle_2_idempotent", **s2)
		if s1.get("journal_entry") != s2.get("journal_entry"):
			out["pass"] = False
			step("FAIL_duplicate_settle_je")

		je_name = s1.get("journal_entry")
		if je_name:
			step(
				"post_settle_manual_checks",
				journal_entry=je_name,
				pm_clearance=cl.name,
				note="JE/clearance cancel sequence is covered by test_settle_je_cancel_then_clearance_cancel_roll_back_reservation.",
			)

		created_refs = {
			emp,
			holder_name,
			req.name,
			pe2,
			pi.name,
			cl.name,
		}
		if je_name:
			created_refs.add(je_name)
		from erpnext_extensions.petty_management.services.reconciliation_service import reconcile

		rec = reconcile(apply_safe_fixes=False, company=tpm.COMPANY)
		touching = []
		for issue in rec.issues:
			if issue.severity != "error":
				continue
			for v in (issue.references or {}).values():
				if isinstance(v, str) and v in created_refs:
					touching.append({"code": issue.code, "detail": issue.detail})
					break
		if touching:
			out["pass"] = False
			step("reconciliation_errors_on_smoke_docs", issues=touching)
		else:
			step(
				"reconciliation_smoke_docs_ok",
				smoke_doc_error_issues=0,
				global_error_count=int(rec.to_dict().get("summary", {}).get("errors", 0)),
			)

		frappe.db.commit()
	except unittest.SkipTest as sk:
		out["pass"] = False
		out["error"] = f"skipped: {sk!s}"
		out["steps"].append({"step": "skipped", "reason": str(sk)})
		frappe.db.rollback()
	except Exception as e:
		out["pass"] = False
		out["error"] = repr(e)
		out["steps"].append({"step": "exception", "error": repr(e)})
		frappe.db.rollback()

	return out
