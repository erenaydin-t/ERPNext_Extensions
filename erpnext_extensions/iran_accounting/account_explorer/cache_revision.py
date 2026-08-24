# Copyright (c) 2026, Farbod Siyahpoosh and contributors
"""Per-company accounting revision for Account Explorer prepared results."""

from __future__ import annotations

import frappe
from frappe.utils import now_datetime

REVISION_DOCTYPE = "Account Explorer Accounting Revision"


def get_accounting_revision(company: str) -> int:
	if not company:
		return 0
	value = frappe.db.get_value(REVISION_DOCTYPE, {"company": company}, "revision")
	if value is None:
		return _ensure_revision_row(company)
	return int(value or 1)


def bump_accounting_revision(doc=None, method: str | None = None, company: str | None = None) -> int:
	"""Increment company accounting revision (invalidates prepared results).

	Doc-event hooks call this as ``(doc, method)``. Programmatic callers may use
	``bump_accounting_revision(company=...)``.
	"""
	# Legacy / convenience: first positional arg may be a company name string.
	if isinstance(doc, str) and not company:
		company = doc
		doc = None

	if not company and doc is not None:
		company = getattr(doc, "company", None)

	# Dimension metadata has no company — invalidate every tracked company.
	if not company and doc is not None and getattr(doc, "doctype", None) == "Accounting Dimension":
		last = 0
		for row in frappe.get_all(REVISION_DOCTYPE, fields=["company"]):
			last = bump_accounting_revision(company=row.company)
		return last

	if not company:
		return 0

	name = frappe.db.get_value(REVISION_DOCTYPE, {"company": company}, "name")
	if not name:
		_ensure_revision_row(company)
		name = frappe.db.get_value(REVISION_DOCTYPE, {"company": company}, "name")

	current = int(frappe.db.get_value(REVISION_DOCTYPE, name, "revision") or 1)
	nxt = current + 1
	frappe.db.set_value(
		REVISION_DOCTYPE,
		name,
		{"revision": nxt, "last_bumped_on": now_datetime()},
		update_modified=False,
	)
	return nxt


def _ensure_revision_row(company: str) -> int:
	existing = frappe.db.get_value(REVISION_DOCTYPE, {"company": company}, ["name", "revision"], as_dict=True)
	if existing:
		return int(existing.revision or 1)
	doc = frappe.get_doc(
		{
			"doctype": REVISION_DOCTYPE,
			"company": company,
			"revision": 1,
			"last_bumped_on": now_datetime(),
		}
	)
	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)
	return 1
