# Copyright (c) 2026, Farbod Siyahpoosh and contributors
"""Prep PM Request cancel/delete Desk E2E scenarios (v4.6.8)."""

from __future__ import annotations

import frappe
from frappe.utils import flt, today

from erpnext_extensions.petty_management.tests import test_pm_clearance as tpm
from erpnext_extensions.petty_management.tests.test_pm_request_multi_pe import (
	_create_funding_pe,
	_ensure_pm_settings_bank,
	_new_submitted_request,
	_sync_funding_fields,
)


def _site_ready():
	frappe.set_user("Administrator")
	tpm._ensure_company_context()
	tpm._ensure_petty_account()
	_ensure_pm_settings_bank()


@frappe.whitelist()
def prepare_unfunded_for_cancel() -> dict:
	"""Finance-approved Request with no PE — Desk cancel should succeed."""
	_site_ready()
	emp = tpm._make_employee()
	tpm._make_holder(emp)
	req = _new_submitted_request(emp, 18_000)
	ws = frappe.db.get_value("PM Request", req, "workflow_state")
	frappe.db.commit()
	return {"pm_request": req, "workflow_state": ws, "docstatus": 1}


@frappe.whitelist()
def prepare_funded_for_cancel_block() -> dict:
	_site_ready()
	emp = tpm._make_employee()
	tpm._make_holder(emp)
	req = _new_submitted_request(emp, 22_000)
	pe = _create_funding_pe(req, 22_000)
	_sync_funding_fields(req)
	frappe.db.commit()
	return {"pm_request": req, "payment_entry": pe, "docstatus": 1}


@frappe.whitelist()
def prepare_after_pe_cancel_for_request_cancel() -> dict:
	_site_ready()
	emp = tpm._make_employee()
	tpm._make_holder(emp)
	req = _new_submitted_request(emp, 16_000)
	pe = _create_funding_pe(req, 16_000)
	_sync_funding_fields(req)
	frappe.get_doc("Payment Entry", pe).cancel()
	_sync_funding_fields(req)
	frappe.db.commit()
	return {
		"pm_request": req,
		"payment_entry": pe,
		"total_paid_amount": flt(frappe.db.get_value("PM Request", req, "total_paid_amount")),
	}


@frappe.whitelist()
def prepare_cancelled_clean_for_delete() -> dict:
	_site_ready()
	emp = tpm._make_employee()
	tpm._make_holder(emp)
	req = _new_submitted_request(emp, 14_000)
	frappe.get_doc("PM Request", req).cancel()
	frappe.db.commit()
	return {
		"pm_request": req,
		"docstatus": cint_doc(req),
		"status": frappe.db.get_value("PM Request", req, "status"),
	}


@frappe.whitelist()
def prepare_cancelled_with_pe_history_for_delete_block() -> dict:
	_site_ready()
	emp = tpm._make_employee()
	tpm._make_holder(emp)
	req = _new_submitted_request(emp, 13_000)
	pe = _create_funding_pe(req, 13_000)
	frappe.get_doc("Payment Entry", pe).cancel()
	_sync_funding_fields(req)
	frappe.get_doc("PM Request", req).cancel()
	frappe.db.commit()
	return {"pm_request": req, "payment_entry": pe, "docstatus": cint_doc(req)}


@frappe.whitelist()
def prepare_clean_draft_for_delete() -> dict:
	_site_ready()
	emp = tpm._make_employee()
	tpm._make_holder(emp)
	req = frappe.new_doc("PM Request")
	req.company = tpm.COMPANY
	req.employee = emp
	req.transaction_date = today()
	req.append("details", {"advance_amount": 7_000})
	req.insert()
	frappe.db.commit()
	return {"pm_request": req.name, "docstatus": 0}


@frappe.whitelist()
def prepare_multi_pe_partial_for_cancel_block() -> dict:
	"""Two submitted PEs with one cancelled — still funded → cancel blocked."""
	_site_ready()
	emp = tpm._make_employee()
	tpm._make_holder(emp)
	req = _new_submitted_request(emp, 100_000)
	pe1 = _create_funding_pe(req, 40_000)
	pe2 = _create_funding_pe(req, 60_000)
	_sync_funding_fields(req)
	frappe.get_doc("Payment Entry", pe1).cancel()
	_sync_funding_fields(req)
	frappe.db.commit()
	return {
		"pm_request": req,
		"payment_entry_cancelled": pe1,
		"payment_entry_submitted": pe2,
		"total_paid_amount": flt(frappe.db.get_value("PM Request", req, "total_paid_amount")),
	}


@frappe.whitelist()
def prepare_cancelled_with_clearance_history_for_delete_block() -> dict:
	"""Cancelled Request with Rejected Clearance allocation still blocks delete."""
	_site_ready()
	emp = tpm._make_employee()
	tpm._make_holder(emp)
	req = _new_submitted_request(emp, 19_000)
	pe = _create_funding_pe(req, 19_000)
	_sync_funding_fields(req)
	pi = tpm._make_pi_outstanding(3_000)
	pi.insert()
	pi.submit()
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
	cl.append("request_allocations", {"pm_request": req, "allocated_amount": 3_000})
	cl.insert()
	cl.submit()
	frappe.db.set_value("PM Clearance", cl.name, "status", "Rejected", update_modified=False)
	frappe.get_doc("Payment Entry", pe).cancel()
	_sync_funding_fields(req)
	frappe.get_doc("PM Request", req).cancel()
	frappe.db.commit()
	return {"pm_request": req, "clearance": cl.name, "docstatus": cint_doc(req)}


def cint_doc(name: str) -> int:
	from frappe.utils import cint

	return cint(frappe.db.get_value("PM Request", name, "docstatus"))
