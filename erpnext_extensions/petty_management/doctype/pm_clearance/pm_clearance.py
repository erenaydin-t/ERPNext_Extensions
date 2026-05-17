# Copyright (c) 2026, Farbod Siyahpoosh and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe import _
from frappe.exceptions import QueryTimeoutError
from frappe.model.document import Document
from frappe.model.naming import make_autoname
from frappe.utils import getdate, today

from erpnext_extensions.petty_management.services.allocation_service import (
	get_pm_request_allocation_context as get_pm_request_allocation_context_service,
	get_pm_request_paid_amount,
	pm_request_passes_clearance_filters,
	pm_request_query_for_pm_clearance as _pm_request_query_for_pm_clearance,
	sum_prior_pm_request_allocations,
)
from erpnext_extensions.petty_management.services.clearance_service import (
	before_cancel_clearance,
	before_validate_clearance,
	clearance_is_approved,
	ensure_petty_cash_account_filled,
	normalize_settlement_types,
	on_cancel_clearance,
	on_submit_clearance,
	prepare_doc_for_je_preview,
	prune_empty_request_allocation_rows,
	sync_clearance_status_from_workflow,
	validate_and_stamp_pi_rows,
	validate_and_stamp_supplier_advance_rows,
	validate_clearance,
	validate_duplicate_settlement_targets,
	validate_request_allocations,
)
from erpnext_extensions.petty_management.services.constants import SETTLEMENT_PI, SETTLEMENT_SA
from erpnext_extensions.petty_management.services.holder_service import (
	clearance_petty_cash_account,
	get_holder_context,
	get_holder_petty_cash_account,
	request_petty_cash_account as pm_request_petty_cash_from_holder,
	sync_clearance_holder_fields,
)
from erpnext_extensions.petty_management.services.journal_entry_service import (
	build_clearance_je_accounts,
	create_clearance_journal_entry,
	settle_petty_cash as settle_petty_cash_service,
)
from erpnext_extensions.petty_management.services.preview_service import (
	doc_for_preview,
	preview_pm_clearance_settlement as preview_pm_clearance_settlement_service,
)


class PMClearance(Document):
	"""Thin controller for PM Clearance settlement lifecycle."""

	def autoname(self):
		if not self.employee:
			frappe.throw(_("Employee is required before naming"))
		# Single monthly series (not per-employee) to avoid tabSeries row lock storms.
		try:
			self.name = make_autoname("CLR-.YYYY.-.MM.-.#####", doc=self)
		except QueryTimeoutError:
			frappe.throw(
				_("PM Clearance numbering is currently busy. Please refresh and try again."),
				title=_("Please try again"),
			)

	def before_validate(self):
		before_validate_clearance(self)

	def validate(self):
		validate_clearance(self)

	def before_submit(self):
		return

	def on_submit(self):
		on_submit_clearance(self)

	def before_cancel(self):
		before_cancel_clearance(self)

	def on_cancel(self):
		on_cancel_clearance(self)

	def _ensure_petty_cash_account_filled(self):
		ensure_petty_cash_account_filled(self)

	def _normalize_settlement_types(self):
		normalize_settlement_types(self)

	def _sync_holder_and_pending(self):
		sync_clearance_holder_fields(self)

	def _validate_duplicate_settlement_targets(self):
		validate_duplicate_settlement_targets(self)

	def _validate_and_stamp_pi_rows(self):
		validate_and_stamp_pi_rows(self)

	def _validate_and_stamp_supplier_advance_rows(self):
		validate_and_stamp_supplier_advance_rows(self)

	def _calc_line_totals(self):
		from erpnext_extensions.petty_management.services.clearance_service import calc_line_totals

		calc_line_totals(self)

	def _calc_parent_totals(self):
		from erpnext_extensions.petty_management.services.clearance_service import calc_parent_totals

		calc_parent_totals(self)

	def _validate_request_allocations(self):
		validate_request_allocations(self)

	def _sync_clearance_status_from_workflow(self):
		sync_clearance_status_from_workflow(self)

	def _prune_empty_request_allocation_rows(self):
		prune_empty_request_allocation_rows(self)

	def _sync_funding_traceability_snapshot(self):
		sync_clearance_holder_fields(self)

	def _create_clearance_journal_entry(self):
		return create_clearance_journal_entry(self)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def pm_request_query_for_pm_clearance(doctype, txt, searchfield, start, page_len, filters):
	return _pm_request_query_for_pm_clearance(doctype, txt, searchfield, start, page_len, filters)


@frappe.whitelist()
def get_pm_request_allocation_context(
	pm_request: str,
	pm_clearance: str | None = None,
	company: str | None = None,
	employee: str | None = None,
	holder: str | None = None,
	petty_cash_account: str | None = None,
) -> dict:
	"""Controller wrapper for PM Clearance grid calls.

	The service function is also whitelisted so direct service calls remain
	backward compatible, but PM Clearance JS should use this controller path.
	"""
	return get_pm_request_allocation_context_service(
		pm_request=pm_request,
		pm_clearance=pm_clearance,
		company=company,
		employee=employee,
		holder=holder,
		petty_cash_account=petty_cash_account,
	)


def _petty_cash_account_for_holder(holder_name: str | None) -> str:
	return get_holder_petty_cash_account(holder_name)


def _clearance_is_approved(doc: Document) -> bool:
	return clearance_is_approved(doc)


def _doc_for_preview(doc=None, pm_clearance: str | None = None) -> Document:
	return doc_for_preview(doc=doc, pm_clearance=pm_clearance)


def _prepare_doc_for_je_preview(dobj: Document) -> None:
	prepare_doc_for_je_preview(dobj)


@frappe.whitelist()
def get_pm_clearance_holder_context(employee: str | None = None, company: str | None = None, posting_date=None) -> dict:
	return get_holder_context(employee, company, posting_date=posting_date)


@frappe.whitelist()
def preview_pm_clearance_settlement(doc=None, pm_clearance: str | None = None) -> dict:
	return preview_pm_clearance_settlement_service(doc=doc, pm_clearance=pm_clearance)


@frappe.whitelist()
def settle_petty_cash(pm_clearance: str) -> dict[str, str]:
	return settle_petty_cash_service(pm_clearance)


@frappe.whitelist()
def get_pm_clearance_action_flags(pm_clearance: str) -> dict:
	from erpnext_extensions.petty_management.services.clearance_action_policy import (
		get_pm_clearance_action_flags as _flags,
	)

	return _flags(pm_clearance)

