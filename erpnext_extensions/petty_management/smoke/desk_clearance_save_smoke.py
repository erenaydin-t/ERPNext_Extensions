"""Desk-like PM Clearance save via HTTP API (Opening Advance + PI path)."""

from __future__ import annotations

import json

import frappe
from frappe.utils import today

import erpnext_extensions.petty_management.tests.test_pm_clearance as pm_ct
from erpnext_extensions.petty_management.smoke.final_acceptance_opening_clearance import (
	_patch_pi_round_floats_compat,
)


def execute():
	"""Create PM Clearance the same way the form save payload would (insert, not ignore_validate)."""
	frappe.set_user("Administrator")
	_patch_pi_round_floats_compat()
	pm_ct._ensure_company_context()
	pm_ct._ensure_petty_account()
	if not pm_ct.COMPANY:
		print(json.dumps({"ok": False, "error": "no company"}))
		return

	emp = pm_ct._make_employee()
	holder = pm_ct._make_holder(emp)
	oa = frappe.new_doc("PM Opening Advance")
	oa.holder = holder
	oa.opening_date = today()
	oa.opening_source_type = "Opening Balance"
	oa.opening_advance_amount = 5_000
	oa.reference_no = "DESK-API-SMOKE"
	oa.insert(ignore_permissions=True)
	oa.submit()

	pi = pm_ct._make_pi_outstanding(1_000)
	bs = frappe.get_single("Buying Settings")
	prev = bs.po_required
	bs.po_required = 0
	bs.save(ignore_permissions=True)
	try:
		pi.insert(ignore_permissions=True)
		pi.submit()
	except Exception as exc:
		print(json.dumps({"ok": False, "step": "pi_submit", "error": str(exc)}))
		return
	finally:
		bs.po_required = prev
		bs.save(ignore_permissions=True)

	cl = frappe.new_doc("PM Clearance")
	cl.company = pm_ct.COMPANY
	cl.employee = emp
	cl.transaction_date = today()
	pm_ct._append_pm_clearance_detail_row(
		cl,
		{
			"settlement_type": "Purchase Invoice",
			"purchase_invoice": pi.name,
			"allocated_amount": 1_000,
		},
	)
	cl.append(
		"request_allocations",
		{
			"funding_source_type": "PM Opening Advance",
			"pm_opening_advance": oa.name,
			"allocated_amount": 1_000,
		},
	)
	cl.insert()
	frappe.db.commit()
	print(
		json.dumps(
			{
				"ok": True,
				"pm_clearance": cl.name,
				"pm_opening_advance": oa.name,
				"purchase_invoice": pi.name,
			},
			indent=2,
		)
	)
