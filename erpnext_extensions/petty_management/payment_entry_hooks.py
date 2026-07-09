"""Payment Entry hooks for Petty Management funding linkage."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, flt

from erpnext_extensions.petty_management.services.allocation_service import (
	get_pm_request_paid_amount,
	sum_prior_pm_request_allocations,
)
from erpnext_extensions.petty_management.services.funding_queries import find_pm_requests_for_payment_entry
from erpnext_extensions.petty_management.services.funding_service import sync_pm_request_funding_fields

_EPS = 1e-6


def _pe_amount(doc) -> float:
	for fieldname in ("paid_amount", "received_amount"):
		if flt(doc.get(fieldname)) > 0:
			return flt(doc.get(fieldname))
	return 0.0


def on_payment_entry_after_insert(doc, method=None):
	"""Notify Desk when a funding PE is created (including manual insert with PM link)."""
	if doc.payment_type != "Pay":
		return
	for name in find_pm_requests_for_payment_entry(doc.name):
		try:
			from erpnext_extensions.petty_management.services.request_api_guard import (
				notify_pm_request_funding_updated,
			)

			notify_pm_request_funding_updated(name, "on_payment_entry_created")
		except Exception:
			pass


def on_payment_entry_submit(doc, method=None):
	"""Keep PM Request aggregates aligned when PE is submitted."""
	from erpnext_extensions.petty_management import petty_audit

	for name in find_pm_requests_for_payment_entry(doc.name):
		sync_pm_request_funding_fields(name)
	for name in find_pm_requests_for_payment_entry(doc.name):
		try:
			from erpnext_extensions.petty_management.services.request_api_guard import (
				notify_pm_request_funding_updated,
			)

			notify_pm_request_funding_updated(name, "on_payment_entry_submitted")
		except Exception:
			pass
	for name in find_pm_requests_for_payment_entry(doc.name):
		try:
			pm_row = frappe.db.get_value("PM Request", name, ["holder", "employee", "company"], as_dict=True)
			petty_audit.log_event(
				"pm_payment_entry_submitted",
				pm_request=name,
				payment_entry=doc.name,
				holder=pm_row.get("holder") if pm_row else None,
				employee=pm_row.get("employee") if pm_row else None,
				company=pm_row.get("company") if pm_row else None,
			)
		except Exception:
			pass


def unlink_pm_request_payment_entry_pointer(pe_name: str) -> list[str]:
	"""Clear Latest Payment Entry pointer so draft PE can be trashed (Frappe link check)."""
	updated: list[str] = []
	for pm_name in frappe.get_all("PM Request", filters={"payment_entry": pe_name}, pluck="name"):
		frappe.db.set_value("PM Request", pm_name, "payment_entry", None, update_modified=False)
		updated.append(pm_name)
	return updated


def _effective_submitted_docstatus(doc) -> int:
	"""During cancel save Frappe sets docstatus=2 before ``before_cancel`` runs."""
	ds = cint(doc.docstatus)
	if ds == 1:
		return 1
	if ds == 2 and getattr(doc, "_action", None) == "cancel":
		prev = getattr(doc, "_doc_before_save", None)
		if prev is not None:
			return cint(prev.docstatus)
	return ds


def on_payment_entry_before_cancel(doc, method=None):
	"""Block cancel when clearance reservations exceed funded amount after cancel."""
	if doc.payment_type != "Pay" or _effective_submitted_docstatus(doc) != 1:
		return
	pm_requests = find_pm_requests_for_payment_entry(doc.name)
	for pm_request in pm_requests:
		paid_total = flt(get_pm_request_paid_amount(pm_request))
		this_amount = _pe_amount(doc)
		paid_after = paid_total - this_amount
		reserved = flt(sum_prior_pm_request_allocations(pm_request, None))
		if reserved > paid_after + _EPS:
			frappe.throw(
				_(
					"This Payment Entry cannot be cancelled because allocated petty cash settlements exceed the remaining funded amount. Please cancel or reduce PM Clearance allocations first."
				),
				title=_("Cannot cancel Payment Entry"),
			)
	if pm_requests:
		unlink_pm_request_payment_entry_pointer(doc.name)
		doc.flags.ignore_links = True


def on_payment_entry_trash(doc, method=None):
	"""Clear PM Request pointer before Frappe link check; full resync runs in after_delete."""
	if doc.payment_type != "Pay":
		return
	if cint(doc.docstatus) == 0:
		unlink_pm_request_payment_entry_pointer(doc.name)


def _pm_request_names_from_pe_doc(doc) -> list[str]:
	names: set[str] = set()
	ref = (doc.reference_no or "").strip()
	if ref and frappe.db.exists("PM Request", ref):
		names.add(ref)
	custom = (doc.get("custom_pm_request") or "").strip()
	if custom and frappe.db.exists("PM Request", custom):
		names.add(custom)
	if doc.name:
		for n in frappe.get_all("PM Request", filters={"payment_entry": doc.name}, pluck="name"):
			names.add(n)
	return sorted(names)


def on_payment_entry_after_delete(doc, method=None):
	if doc.payment_type != "Pay":
		return
	for name in _pm_request_names_from_pe_doc(doc):
		sync_pm_request_funding_fields(name)
		try:
			from erpnext_extensions.petty_management.services.request_api_guard import (
				notify_pm_request_funding_updated,
			)

			notify_pm_request_funding_updated(name, "on_payment_entry_trashed")
		except Exception:
			pass


def on_payment_entry_cancel(doc, method=None):
	"""Resync PM Request funding fields when Payment Entry is cancelled."""
	from erpnext_extensions.petty_management import petty_audit

	pm_names = find_pm_requests_for_payment_entry(doc.name)
	unlink_pm_request_payment_entry_pointer(doc.name)
	for name in pm_names:
		sync_pm_request_funding_fields(name, exclude_payment_entry=doc.name)
	for name in pm_names:
		try:
			from erpnext_extensions.petty_management.services.request_api_guard import (
				notify_pm_request_funding_updated,
			)

			notify_pm_request_funding_updated(name, "on_payment_entry_cancelled")
		except Exception:
			pass
	for name in pm_names:
		try:
			pm_row = frappe.db.get_value("PM Request", name, ["holder", "employee", "company"], as_dict=True)
			petty_audit.log_event(
				"pm_payment_entry_cancelled",
				pm_request=name,
				payment_entry=doc.name,
				holder=pm_row.get("holder") if pm_row else None,
				employee=pm_row.get("employee") if pm_row else None,
				company=pm_row.get("company") if pm_row else None,
			)
		except Exception:
			pass
