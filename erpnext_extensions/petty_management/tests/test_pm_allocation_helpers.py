# Copyright (c) 2026, Farbod Siyahpoosh and contributors
"""Shared helpers for PM Clearance funding allocation tests (no PI submit)."""

from __future__ import annotations

import frappe
from frappe.utils import flt, today

import erpnext_extensions.petty_management.tests.test_pm_clearance as pm_ct


def ensure_site_context() -> None:
	pm_ct._ensure_company_context()
	if not pm_ct.COMPANY:
		raise RuntimeError("No Company on site")


def make_submitted_opening(
	holder: str,
	opening: float,
	previously_settled: float = 0,
	*,
	reference_suffix: str = "ALLOC-TEST",
) -> str:
	doc = frappe.new_doc("PM Opening Advance")
	doc.holder = holder
	doc.opening_date = today()
	doc.opening_source_type = "Opening Balance"
	doc.opening_advance_amount = opening
	doc.previously_settled_before_migration = previously_settled
	doc.reference_no = reference_suffix
	doc.insert(ignore_permissions=True)
	doc.submit()
	return doc.name


def build_clearance_for_allocation_validation(
	employee: str,
	holder: str,
	settlement_total: float,
):
	"""PM Clearance shell for ``validate_request_allocations`` only (skips PI row validation)."""
	from erpnext_extensions.petty_management.services.holder_service import sync_clearance_holder_fields

	cl = frappe.new_doc("PM Clearance")
	cl.company = pm_ct.COMPANY
	cl.employee = employee
	cl.transaction_date = today()
	sync_clearance_holder_fields(cl)
	cl.total_expense_amount = flt(settlement_total)
	cl.total_petty_cash = flt(settlement_total)
	cl.total_expense_amount = flt(settlement_total)
	return cl


def append_opening_allocation_row(
	cl,
	oa_name: str,
	amount: float,
	*,
	pm_request: str | None = None,
):
	cl.append(
		"request_allocations",
		{
			"funding_source_type": "PM Opening Advance",
			"pm_opening_advance": oa_name,
			"pm_request": pm_request,
			"allocated_amount": amount,
		},
	)


def append_pm_request_allocation_row(
	cl,
	pm_request: str,
	amount: float,
	*,
	pm_opening_advance: str | None = None,
):
	cl.append(
		"request_allocations",
		{
			"funding_source_type": "PM Request",
			"pm_request": pm_request,
			"pm_opening_advance": pm_opening_advance,
			"allocated_amount": amount,
		},
	)


def run_allocation_validation(cl) -> None:
	from erpnext_extensions.petty_management.services.allocation_service import validate_request_allocations

	validate_request_allocations(cl)


def normalize_funding_rows(cl) -> None:
	from erpnext_extensions.petty_management.services.clearance_service import normalize_funding_allocation_rows

	normalize_funding_allocation_rows(cl)
