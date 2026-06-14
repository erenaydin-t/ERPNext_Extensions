"""PM Clearance autoname — hash-based IDs (no tabSeries / FOR UPDATE)."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, today

_MAX_NAME_LEN = 140


def assign_pm_clearance_name(doc: Document) -> None:
	"""Assign a unique PM Clearance name without locking ``tabSeries``."""
	employee = (doc.employee or "").strip()
	if not employee:
		frappe.throw(_("Employee is required before naming"), title=_("PM Clearance"))

	for _ in range(8):
		candidate = _unique_hash_name(doc, employee)
		if not frappe.db.exists("PM Clearance", candidate):
			doc.name = candidate
			return

	frappe.throw(
		_("Could not generate a unique PM Clearance name. Please try again."),
		title=_("Please try again"),
	)


def _unique_hash_name(doc: Document, employee: str) -> str:
	yymm = getdate(getattr(doc, "transaction_date", None) or today()).strftime("%Y%m")
	suffix = frappe.generate_hash(length=12)
	candidate = f"CLR-{employee}-{yymm}-{suffix}"
	if len(candidate) > _MAX_NAME_LEN:
		candidate = f"CLR-{yymm}-{suffix}"
	return candidate
