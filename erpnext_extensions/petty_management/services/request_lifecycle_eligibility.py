# Copyright (c) 2026, ERPNext Extensions contributors
"""v4.6.8 — PM Request cancel / delete eligibility (independent helpers).

Cancel and delete rules must never share decision logic beyond shared PE/Clearance lookups.
"""

from __future__ import annotations

from typing import Any

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt

from erpnext_extensions.petty_management.services.funding_queries import (
	has_draft_payment_entry,
	list_payment_entries_for_pm_request,
	sum_submitted_pe_amount,
)

_EPS = 1e-6

# Clearance statuses that do NOT block Request cancel (approved design matrix).
_CANCEL_CLEARANCE_ALLOW_STATUSES = frozenset({"Cancelled", "Rejected"})


def _pm_request_name(doc: Document | str) -> str:
	if isinstance(doc, str):
		return doc
	return doc.name


def _linked_payment_entries(pm_request: str) -> list[dict]:
	"""All funding PEs (draft / submitted / cancelled) linked to this Request."""
	return list_payment_entries_for_pm_request(pm_request)


def _clearance_allocations_for_request(pm_request: str) -> list[dict]:
	"""Every Clearance allocation row pointing at this Request (any parent status)."""
	return frappe.db.sql(
		"""
		SELECT
			a.parent AS clearance,
			cl.docstatus AS clearance_docstatus,
			IFNULL(cl.status, '') AS clearance_status,
			a.allocated_amount
		FROM `tabPM Clearance Request Allocation` a
		INNER JOIN `tabPM Clearance` cl
			ON cl.name = a.parent AND a.parenttype = 'PM Clearance'
		WHERE a.parentfield = 'request_allocations'
			AND IFNULL(a.is_legacy_row, 0) = 0
			AND a.pm_request = %s
		ORDER BY a.parent
		""",
		(pm_request,),
		as_dict=True,
	)


def _blocking_clearances_for_cancel(pm_request: str) -> list[dict]:
	"""Clearances that block Request cancel (approved matrix).

	Block: Draft, Pending*, Approved, Pending JE, Settled (any non-Rejected/Cancelled).
	Allow: Rejected, Cancelled (docstatus=2 or status Cancelled/Rejected).
	"""
	rows = _clearance_allocations_for_request(pm_request)
	blocking: list[dict] = []
	for row in rows:
		status = (row.clearance_status or "").strip()
		ds = cint(row.clearance_docstatus)
		if ds == 2 or status in _CANCEL_CLEARANCE_ALLOW_STATUSES:
			continue
		blocking.append(row)
	return blocking


def _format_names(names: list[str], limit: int = 8) -> str:
	uniq = sorted({n for n in names if n})
	if not uniq:
		return ""
	shown = uniq[:limit]
	extra = len(uniq) - len(shown)
	text = ", ".join(frappe.bold(n) for n in shown)
	if extra > 0:
		text += _(" and {0} more").format(extra)
	return text


def get_pm_request_cancel_blockers(doc: Document | str) -> list[str]:
	"""Return human-readable cancel blockers (empty ⇒ eligible). Does not check DocPerm."""
	name = _pm_request_name(doc)
	if isinstance(doc, str):
		row = frappe.db.get_value("PM Request", name, ["docstatus", "journal_entry"], as_dict=True)
		if not row:
			return [_("PM Request {0} not found").format(name)]
		docstatus = cint(row.docstatus)
		journal_entry = row.journal_entry
	else:
		# Frappe Document.cancel() sets in-memory docstatus=2 before before_cancel/save.
		# Authoritative eligibility uses DB docstatus (still 1 until cancel commits).
		db_row = (
			frappe.db.get_value("PM Request", name, ["docstatus", "journal_entry"], as_dict=True)
			if name
			else None
		)
		if db_row:
			docstatus = cint(db_row.docstatus)
			journal_entry = getattr(doc, "journal_entry", None) or db_row.journal_entry
		else:
			docstatus = cint(doc.docstatus)
			journal_entry = getattr(doc, "journal_entry", None)

	blockers: list[str] = []
	if docstatus != 1:
		blockers.append(_("Only a submitted PM Request can be cancelled (current docstatus={0}).").format(docstatus))
		return blockers

	submitted = flt(sum_submitted_pe_amount(name))
	if submitted > _EPS:
		pes = [r["payment_entry"] for r in _linked_payment_entries(name) if (r.get("status") or "") == "Submitted"]
		msg = _("Cannot cancel: submitted funding is {0}.").format(frappe.bold(frappe.format_value(submitted, {"fieldtype": "Currency"})))
		if pes:
			msg += " " + _("Submitted Payment Entry(ies): {0}.").format(_format_names(pes))
		blockers.append(msg)

	if has_draft_payment_entry(name):
		drafts = [r["payment_entry"] for r in _linked_payment_entries(name) if (r.get("status") or "") == "Draft"]
		blockers.append(
			_("Cannot cancel: draft Payment Entry(ies) exist: {0}. Submit or cancel them first.").format(
				_format_names(drafts) or _("(draft)")
			)
		)

	blocking_clr = _blocking_clearances_for_cancel(name)
	if blocking_clr:
		blockers.append(
			_("Cannot cancel: blocking PM Clearance(s): {0}.").format(
				_format_names([r.clearance for r in blocking_clr])
			)
		)

	meta = frappe.get_meta("PM Request")
	if meta.has_field("journal_entry") and journal_entry:
		je_ds = cint(frappe.db.get_value("Journal Entry", journal_entry, "docstatus"))
		if je_ds == 1:
			blockers.append(
				_("Cannot cancel: submitted Journal Entry {0} is linked on this Request.").format(
					frappe.bold(journal_entry)
				)
			)

	return blockers


def assert_pm_request_cancel_allowed(doc: Document | str) -> None:
	"""Throw if PM Request cancel is not allowed (v4.6.8)."""
	blockers = get_pm_request_cancel_blockers(doc)
	if blockers:
		frappe.throw("<br>".join(blockers), title=_("Cannot cancel PM Request"))


def get_pm_request_delete_blockers(doc: Document | str) -> list[str]:
	"""Return human-readable delete blockers (empty ⇒ eligible). Does not check DocPerm.

	Policy:
	- Submitted (docstatus=1): never.
	- Cancelled (docstatus=2): only if zero PE (any status) and zero Clearance allocations.
	- Draft (docstatus=0): mistaken cleanup only — same zero PE / zero Clearance rule.
	"""
	name = _pm_request_name(doc)
	if isinstance(doc, str):
		row = frappe.db.get_value("PM Request", name, ["docstatus", "journal_entry"], as_dict=True)
		if not row:
			return [_("PM Request {0} not found").format(name)]
		docstatus = cint(row.docstatus)
		journal_entry = row.journal_entry
	else:
		docstatus = cint(doc.docstatus)
		journal_entry = getattr(doc, "journal_entry", None)

	blockers: list[str] = []

	if docstatus == 1:
		blockers.append(
			_("Submitted PM Request cannot be deleted. Cancel it first (when eligible), then delete.")
		)
		return blockers

	if docstatus not in (0, 2):
		blockers.append(_("PM Request cannot be deleted (docstatus={0}).").format(docstatus))
		return blockers

	pes = _linked_payment_entries(name)
	if pes:
		# Any historical PE permanently blocks delete (including cancelled).
		parts = []
		for status in ("Submitted", "Draft", "Cancelled"):
			names = [r["payment_entry"] for r in pes if (r.get("status") or "") == status]
			if names:
				parts.append(f"{status}: {_format_names(names)}")
		blockers.append(
			_(
				"Cannot delete: accounting history exists — Payment Entry(ies) still linked "
				"({0}). Delete remains blocked even for cancelled Payment Entries."
			).format("; ".join(parts))
		)

	allocs = _clearance_allocations_for_request(name)
	if allocs:
		blockers.append(
			_(
				"Cannot delete: PM Clearance history exists: {0}. "
				"Delete remains blocked for any Clearance status (including cancelled/rejected)."
			).format(_format_names([r.clearance for r in allocs]))
		)

	meta = frappe.get_meta("PM Request")
	if meta.has_field("journal_entry") and journal_entry:
		if frappe.db.exists("Journal Entry", journal_entry):
			blockers.append(
				_("Cannot delete: Journal Entry {0} is still linked on this Request.").format(
					frappe.bold(journal_entry)
				)
			)

	return blockers


def assert_pm_request_delete_allowed(doc: Document | str) -> None:
	"""Throw if PM Request delete/trash is not allowed (v4.6.8)."""
	blockers = get_pm_request_delete_blockers(doc)
	if blockers:
		frappe.throw("<br>".join(blockers), title=_("Cannot delete PM Request"))


def apply_cancelled_business_status(doc: Document) -> None:
	"""Set business status=Cancelled after cancel without touching workflow_state."""
	from erpnext_extensions.petty_management.services.business_status_service import (
		REQ_CANCELLED,
		sync_pm_request_business_status,
	)

	doc.docstatus = 2
	status = sync_pm_request_business_status(doc)
	if status != REQ_CANCELLED:
		doc.status = REQ_CANCELLED
		status = REQ_CANCELLED
	if getattr(doc, "name", None):
		frappe.db.set_value("PM Request", doc.name, "status", status, update_modified=False)
