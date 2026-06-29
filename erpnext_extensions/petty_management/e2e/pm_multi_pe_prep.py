# Copyright (c) 2026, Farbod Siyahpoosh and contributors
"""Prepare PM Request documents for Playwright multi-PE E2E."""

from __future__ import annotations

import frappe
from frappe.utils import flt, today

from erpnext_extensions.petty_management.tests import test_pm_clearance as tpm
from erpnext_extensions.petty_management.tests.test_pm_request_multi_pe import (
	_approve_pm_request,
	_create_funding_pe,
	_ensure_pm_settings_bank,
	_new_submitted_request,
	_sync_funding_fields,
)


@frappe.whitelist()
def prepare_two_submitted_partial() -> dict:
	"""Approved 1M request with 50k + 500k submitted PEs (multi-PE UAT)."""
	frappe.set_user("Administrator")
	tpm._ensure_company_context()
	tpm._ensure_petty_account()
	_ensure_pm_settings_bank()
	emp = tpm._make_employee()
	tpm._make_holder(emp)
	req = _new_submitted_request(emp, 1_000_000)
	pe1 = _create_funding_pe(req, 50_000)
	pe2 = _create_funding_pe(req, 500_000)
	_sync_funding_fields(req)
	doc = frappe.get_doc("PM Request", req)
	frappe.db.commit()
	return {
		"pm_request": req,
		"payment_entries": [pe1, pe2],
		"total_paid_amount": flt(doc.total_paid_amount),
		"remaining_to_pay": flt(getattr(doc, "remaining_to_pay", None) or 0),
		"payment_status": doc.payment_status,
	}


@frappe.whitelist()
def prepare_partial_funded_for_close_ui() -> dict:
	"""Approved 100k request with 40k submitted PE (partial)."""
	frappe.set_user("Administrator")
	tpm._ensure_company_context()
	tpm._ensure_petty_account()
	_ensure_pm_settings_bank()
	emp = tpm._make_employee()
	tpm._make_holder(emp)
	req = _new_submitted_request(emp, 100_000)
	pe = _create_funding_pe(req, 40_000)
	_sync_funding_fields(req)
	doc = frappe.get_doc("PM Request", req)
	frappe.db.commit()
	return {
		"pm_request": req,
		"payment_entry": pe,
		"total_paid_amount": flt(doc.total_paid_amount),
		"remaining_to_pay": flt(getattr(doc, "remaining_to_pay", None) or 0),
		"payment_status": doc.payment_status,
	}


@frappe.whitelist()
def prepare_fully_paid_for_close_ui() -> dict:
	frappe.set_user("Administrator")
	tpm._ensure_company_context()
	tpm._ensure_petty_account()
	_ensure_pm_settings_bank()
	emp = tpm._make_employee()
	tpm._make_holder(emp)
	req = _new_submitted_request(emp, 10_000)
	pe = _create_funding_pe(req, 10_000)
	_sync_funding_fields(req)
	doc = frappe.get_doc("PM Request", req)
	frappe.db.commit()
	return {
		"pm_request": req,
		"payment_entry": pe,
		"total_paid_amount": flt(doc.total_paid_amount),
		"remaining_to_pay": flt(getattr(doc, "remaining_to_pay", None) or 0),
		"payment_status": doc.payment_status,
	}


@frappe.whitelist()
def prepare_draft_pe_blocks_close() -> dict:
	frappe.set_user("Administrator")
	tpm._ensure_company_context()
	tpm._ensure_petty_account()
	_ensure_pm_settings_bank()
	emp = tpm._make_employee()
	tpm._make_holder(emp)
	req = _new_submitted_request(emp, 50_000)
	from erpnext_extensions.petty_management.services.request_service import create_payment_entry
	import inspect

	sig = inspect.signature(create_payment_entry)
	if "paid_amount" in sig.parameters:
		draft = create_payment_entry(req, paid_amount=5_000)
	else:
		draft = create_payment_entry(req)
	frappe.db.commit()
	return {"pm_request": req, "draft_pe": draft}
