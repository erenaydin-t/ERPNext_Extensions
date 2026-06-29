# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

import frappe

from erpnext_extensions.petty_management.tests import test_pm_clearance as tpm
from erpnext_extensions.petty_management.tests.pm_request_security_fixtures import (
	petty_management_user_with_company_only,
)
from erpnext_extensions.petty_management.tests.test_pm_request_multi_pe import (
	_ensure_pm_settings_bank,
	_new_submitted_request,
)


@frappe.whitelist()
def get_invalid_pm_request_name() -> dict:
	return {"invalid_name": "REQ-INVALID-E2E-00000"}


@frappe.whitelist()
def get_cross_company_denied_user(pm_request: str) -> dict:
	"""PM user restricted to a company other than the request's company."""
	frappe.only_for("System Manager")
	company = frappe.db.get_value("PM Request", pm_request, "company")
	if not company:
		frappe.throw("PM Request not found")
	other = "PM CrossCo Test B"
	if other == company:
		other = frappe.get_all("Company", filters={"name": ["!=", company]}, pluck="name", limit=1)
		other = other[0] if other else company
	if not frappe.db.exists("Company", other):
		base = frappe.get_doc("Company", company)
		c = frappe.new_doc("Company")
		c.company_name = other
		c.abbr = "PMXB"
		c.default_currency = base.default_currency
		c.country = base.country or "Iran"
		c.insert(ignore_permissions=True)
		frappe.db.commit()
	email = petty_management_user_with_company_only(other, tag="e2e_denied")
	return {"email": email, "password": "pm_sec_test_1", "restricted_company": other}


@frappe.whitelist()
def prepare_draft_pe_for_cancel(pm_request: str) -> dict:
	frappe.only_for("System Manager")
	from erpnext_extensions.petty_management.services.funding_queries import list_payment_entries_for_pm_request
	from erpnext_extensions.petty_management.services.request_service import create_payment_entry

	for row in list_payment_entries_for_pm_request(pm_request):
		if (row.get("status") or "").strip() == "Draft":
			return {"payment_entry": row["payment_entry"], "pm_request": pm_request}

	settings = frappe.get_single("PM Settings")
	auto = settings.auto_submit_payment_entry
	settings.auto_submit_payment_entry = 0
	settings.save(ignore_permissions=True)
	try:
		pe_name = create_payment_entry(pm_request, paid_amount=3_000)
		frappe.db.commit()
		return {"payment_entry": pe_name, "pm_request": pm_request}
	finally:
		settings.auto_submit_payment_entry = auto
		settings.save(ignore_permissions=True)
		frappe.db.commit()


@frappe.whitelist()
def cancel_payment_entry_for_e2e(payment_entry: str) -> dict:
	frappe.only_for("System Manager")
	from erpnext_extensions.petty_management.services.funding_queries import find_pm_requests_for_payment_entry
	from erpnext_extensions.petty_management.services.funding_service import sync_pm_request_funding_fields
	from erpnext_extensions.petty_management.services.request_api_guard import notify_pm_request_funding_updated

	pe = frappe.get_doc("Payment Entry", payment_entry)
	pm_requests = find_pm_requests_for_payment_entry(payment_entry)
	if pe.docstatus == 0:
		pe.delete(ignore_permissions=True)
		event = "on_payment_entry_cancelled"
	elif pe.docstatus == 1:
		pe.cancel()
		event = "on_payment_entry_cancelled"
	else:
		event = "on_payment_entry_cancelled"
	frappe.db.commit()
	for name in pm_requests:
		sync_pm_request_funding_fields(name)
		notify_pm_request_funding_updated(name, event)
	frappe.db.commit()
	return {"payment_entry": payment_entry, "cancelled": True}


@frappe.whitelist()
def submit_payment_entry_for_e2e(payment_entry: str) -> dict:
	frappe.only_for("System Manager")
	from erpnext_extensions.petty_management.services.funding_service import sync_pm_request_funding_fields
	from erpnext_extensions.petty_management.services.funding_queries import find_pm_requests_for_payment_entry
	from erpnext_extensions.petty_management.services.request_api_guard import notify_pm_request_funding_updated

	pe = frappe.get_doc("Payment Entry", payment_entry)
	pm_requests = find_pm_requests_for_payment_entry(payment_entry)
	if pe.docstatus == 0:
		pe.submit()
	frappe.db.commit()
	for name in pm_requests:
		sync_pm_request_funding_fields(name)
		notify_pm_request_funding_updated(name, "on_payment_entry_submitted")
	frappe.db.commit()
	return {"payment_entry": payment_entry, "submitted": True}
