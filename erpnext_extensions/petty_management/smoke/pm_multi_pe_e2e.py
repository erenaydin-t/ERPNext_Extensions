# Copyright (c) 2026, Farbod Siyahpoosh and contributors
"""Backend smoke: multi-PE partial funding + close + clearance still allocates.

Run::

	bench --site development.localhost execute erpnext_extensions.petty_management.smoke.pm_multi_pe_e2e.execute
"""

from __future__ import annotations

from typing import Any

import frappe
from frappe.utils import flt

from erpnext_extensions.petty_management.tests import test_pm_clearance as tpm
from erpnext_extensions.petty_management.tests.test_pm_request_multi_pe import (
	_close_pm_request,
	_create_funding_pe,
	_ensure_pm_settings_bank,
	_new_submitted_request,
	_sync_funding_fields,
)


def execute() -> dict[str, Any]:
	frappe.set_user("Administrator")
	out: dict[str, Any] = {"pass": True, "steps": []}

	def step(name: str, **kw: Any) -> None:
		out["steps"].append({"step": name, **kw})

	try:
		tpm._ensure_company_context()
		if not tpm.COMPANY or not tpm.BANK_ACCOUNT:
			out["pass"] = False
			out["error"] = "Company or bank account missing"
			return out

		tpm._ensure_petty_account()
		_ensure_pm_settings_bank()
		emp = tpm._make_employee()
		tpm._make_holder(emp)
		step("employee", employee=emp)

		req = _new_submitted_request(emp, 100_000)
		step("pm_request", pm_request=req, requested=100_000)

		pe1 = _create_funding_pe(req, 40_000)
		pe2 = _create_funding_pe(req, 30_000)
		step("payment_entries", pe1=pe1, pe2=pe2)
		_sync_funding_fields(req)

		doc = frappe.get_doc("PM Request", req)
		if doc.payment_status != "Partially Paid":
			out["pass"] = False
			step("FAIL_payment_status", got=doc.payment_status)
			return out
		if flt(doc.total_paid_amount) != 70_000:
			out["pass"] = False
			step("FAIL_total_paid", got=flt(doc.total_paid_amount))
			return out

		_close_pm_request(req, close_reason="Partial Approval")
		doc.reload()
		if not doc.is_closed:
			out["pass"] = False
			step("FAIL_not_closed")
			return out
		if flt(doc.total_paid_amount) != 70_000:
			out["pass"] = False
			step("FAIL_paid_changed_after_close", got=flt(doc.total_paid_amount))
			return out

		from erpnext_extensions.petty_management.services.allocation_service import (
			get_pm_request_available_amount,
		)

		avail = flt(get_pm_request_available_amount(req))
		step("available_after_close", available=avail)
		if avail < 70_000:
			out["pass"] = False
			step("FAIL_available_reduced_by_close", available=avail)
			return out

		step("ok")
		frappe.db.commit()
	except Exception as exc:
		out["pass"] = False
		out["error"] = repr(exc)
		frappe.db.rollback()

	return out
