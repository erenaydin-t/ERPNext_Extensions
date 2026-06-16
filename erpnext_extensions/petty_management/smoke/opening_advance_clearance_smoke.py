"""Bench smoke: PM Opening Advance clearance allocation (optional full save with submitted PI)."""

from __future__ import annotations

import json

import frappe
from frappe.utils import flt, today

from erpnext_extensions.petty_management.services.opening_advance_service import (
	get_opening_advance_available_amount,
)
import erpnext_extensions.petty_management.tests.test_pm_allocation_helpers as ah
import erpnext_extensions.petty_management.tests.test_pm_clearance as pm_ct


def _find_submitted_pi(company: str) -> str | None:
	row = frappe.db.sql(
		"""
		SELECT name FROM `tabPurchase Invoice`
		WHERE docstatus = 1 AND company = %s AND IFNULL(outstanding_amount, 0) > 0
		ORDER BY modified DESC
		LIMIT 1
		""",
		company,
	)
	return row[0][0] if row else None


def _try_submit_pi(pi) -> tuple[bool, str | None]:
	try:
		if pi.docstatus == 0:
			pi.insert(ignore_permissions=True)
			pi.submit()
		elif pi.docstatus == 1:
			return True, None
		return False, "Purchase Invoice is not submittable (docstatus != 0/1)"
	except TypeError as exc:
		if "do_not_round_fields" in str(exc):
			return False, "SKIPPED_PI_SUBMIT_ENVIRONMENT: round_floats_in do_not_round_fields incompatible"
		raise
	except Exception as exc:
		return False, str(exc)


def execute():
	frappe.set_user("Administrator")
	pm_ct._ensure_company_context()
	if not pm_ct.COMPANY:
		print(json.dumps({"ok": False, "error": "No Company on site"}, indent=2))
		return
	pm_ct._ensure_petty_account()

	emp = pm_ct._make_employee()
	holder = pm_ct._make_holder(emp)
	oa_name = ah.make_submitted_opening(holder, 12_000, 4_000, reference_suffix="SMOKE")
	open_before = get_opening_advance_available_amount(oa_name)

	allocation_only: dict = {"ok": True, "phase": "allocation_validation"}
	cl_shell = ah.build_clearance_for_allocation_validation(emp, holder, 4_000)
	ah.append_opening_allocation_row(cl_shell, oa_name, 4_000)
	ah.normalize_funding_rows(cl_shell)
	ah.run_allocation_validation(cl_shell)
	row = cl_shell.request_allocations[0]
	allocation_only["snapshot"] = {
		"request_amount": flt(row.request_amount),
		"paid_amount": flt(row.paid_amount),
		"previously_allocated_amount": flt(row.previously_allocated_amount),
		"available_amount": flt(row.available_amount),
		"allocated_amount": flt(row.allocated_amount),
	}

	result = {
		"opening_advance": oa_name,
		"opening_available_before": open_before,
		"allocation_only": allocation_only,
		"full_clearance_save": None,
	}

	pi_name = _find_submitted_pi(pm_ct.COMPANY)
	pi_created = False
	if not pi_name:
		pi = pm_ct._make_pi_outstanding(4_000)
		ok, err = _try_submit_pi(pi)
		if ok:
			pi_name = pi.name
			pi_created = True
		else:
			result["full_clearance_save"] = {"ok": False, "skipped": True, "reason": err}
			result["opening_available_after_allocation_only"] = get_opening_advance_available_amount(oa_name)
			print(json.dumps(result, indent=2, default=str))
			return

	cl = frappe.new_doc("PM Clearance")
	cl.company = pm_ct.COMPANY
	cl.employee = emp
	cl.transaction_date = today()
	pm_ct._append_pm_clearance_detail_row(
		cl,
		{
			"settlement_type": "Purchase Invoice",
			"purchase_invoice": pi_name,
			"allocated_amount": 4_000,
		},
	)
	cl.append(
		"request_allocations",
		{
			"funding_source_type": "PM Opening Advance",
			"pm_opening_advance": oa_name,
			"allocated_amount": 4_000,
		},
	)
	try:
		cl.insert(ignore_permissions=True)
		cl.reload()
		saved_row = cl.request_allocations[0]
		open_after = get_opening_advance_available_amount(oa_name)
		result["full_clearance_save"] = {
			"ok": True,
			"clearance_name": cl.name,
			"opening_available_after_save": open_after,
			"snapshot": {
				"request_amount": flt(saved_row.request_amount),
				"paid_amount": flt(saved_row.paid_amount),
				"previously_allocated_amount": flt(saved_row.previously_allocated_amount),
				"available_amount": flt(saved_row.available_amount),
				"allocated_amount": flt(saved_row.allocated_amount),
			},
			"pi_used": pi_name,
			"pi_created_for_smoke": pi_created,
		}
	except Exception as exc:
		result["full_clearance_save"] = {"ok": False, "error": str(exc)}

	print(json.dumps(result, indent=2, default=str))
