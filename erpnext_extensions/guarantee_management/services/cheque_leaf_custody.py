# Copyright (c) 2026, ERPNext Extensions contributors
"""Cheque Leaf custody for Issued Cheque Guarantee Documents (no GL)."""

from __future__ import annotations

import frappe
from frappe import _, validate_and_sanitize_search_inputs
from frappe.utils import cint, cstr, now_datetime

STATUS_USED_FOR_GUARANTEE = "Used for Guarantee"
HOLDING_STATUSES = frozenset({"Active", "Expired", "Lost"})
RELEASE_STATUSES = frozenset({"Released", "Returned", "Cancelled"})


def is_issued_cheque_guarantee(doc) -> bool:
	return (getattr(doc, "guarantee_direction", None) or "").strip() == "Issued" and (
		getattr(doc, "guarantee_type", None) or ""
	).strip() == "Cheque"


def _lock_leaf(leaf_name: str):
	from erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque import (
		_pdc_get_cheque_leaf_row_for_update,
	)

	return _pdc_get_cheque_leaf_row_for_update(leaf_name)


def assert_leaf_available_for_guarantee(row, gd_name: str) -> None:
	status = (getattr(row, "status", None) or "").strip()
	gd_name = (gd_name or "").strip()
	linked_gd = (getattr(row, "linked_guarantee_document", None) or "").strip()
	if linked_gd and linked_gd != gd_name:
		frappe.throw(
			_("Cheque Leaf is already allocated to Guarantee Document {0}.").format(linked_gd),
			title=_("Cheque Leaf"),
		)
	if status == STATUS_USED_FOR_GUARANTEE and linked_gd in ("", gd_name):
		if linked_gd == gd_name or not linked_gd:
			return
	if status != "Available":
		frappe.throw(
			_("Only Available cheque leaves can be allocated to a Guarantee Document (current status: {0}).").format(
				status
			),
			title=_("Cheque Leaf"),
		)
	if (getattr(row, "linked_post_dated_cheque", None) or "").strip():
		frappe.throw(
			_("This Cheque Leaf is used by Post Dated Cheque {0}.").format(row.linked_post_dated_cheque),
			title=_("Cheque Leaf"),
		)
	if (getattr(row, "reserved_by_pdc", None) or "").strip():
		frappe.throw(
			_("This Cheque Leaf is reserved by Post Dated Cheque {0}.").format(row.reserved_by_pdc),
			title=_("Cheque Leaf"),
		)


def allocate_leaf_to_guarantee(leaf_name: str, gd) -> None:
	leaf_name = (leaf_name or "").strip()
	if not leaf_name:
		frappe.throw(_("Cheque Leaf is required for an Issued Cheque guarantee."), title=_("Guarantee Document"))
	row = _lock_leaf(leaf_name)
	if not row:
		frappe.throw(_("Cheque Leaf {0} does not exist.").format(leaf_name), title=_("Cheque Leaf"))
	if (row.company or "") != (gd.company or ""):
		frappe.throw(
			_("Cheque Leaf must belong to the same Company as this Guarantee Document."),
			title=_("Cheque Leaf"),
		)
	assert_leaf_available_for_guarantee(row, gd.name)
	if row.status == STATUS_USED_FOR_GUARANTEE and (row.linked_guarantee_document or "") == (gd.name or ""):
		return
	now = now_datetime()
	allocated_by = getattr(getattr(frappe, "session", None), "user", None) or "Administrator"
	frappe.flags.guarantee_cheque_leaf_custody = True
	try:
		frappe.db.set_value(
			"Cheque Leaf",
			leaf_name,
			{
				"status": STATUS_USED_FOR_GUARANTEE,
				"linked_guarantee_document": gd.name,
				"guarantee_allocated_on": now,
				"guarantee_allocated_by": allocated_by,
				"guarantee_released_on": None,
			},
			update_modified=True,
		)
	finally:
		frappe.flags.guarantee_cheque_leaf_custody = False


def release_leaf_from_guarantee(leaf_name: str, gd_name: str) -> None:
	leaf_name = (leaf_name or "").strip()
	gd_name = (gd_name or "").strip()
	if not leaf_name:
		return
	row = _lock_leaf(leaf_name)
	if not row:
		return
	linked = (row.linked_guarantee_document or "").strip()
	if linked and linked != gd_name:
		return
	if (row.status or "").strip() not in (STATUS_USED_FOR_GUARANTEE, "Available"):
		return
	if (row.status or "").strip() == "Available" and not linked:
		return
	now = now_datetime()
	frappe.flags.guarantee_cheque_leaf_custody = True
	try:
		frappe.db.set_value(
			"Cheque Leaf",
			leaf_name,
			{
				"status": "Available",
				"linked_guarantee_document": None,
				"guarantee_released_on": now,
			},
			update_modified=True,
		)
	finally:
		frappe.flags.guarantee_cheque_leaf_custody = False


def sync_guarantee_cheque_leaf(doc, before=None) -> None:
	"""Allocate on Active (Issued+Cheque); release on Returned/Released/Cancelled; keep on Expired/Lost."""
	if not is_issued_cheque_guarantee(doc):
		prev_leaf = ((getattr(before, "cheque_leaf", None) if before else None) or "").strip()
		if prev_leaf and (getattr(before, "guarantee_direction", None) or "") == "Issued":
			release_leaf_from_guarantee(prev_leaf, doc.name)
		return

	leaf = (getattr(doc, "cheque_leaf", None) or "").strip()
	status = (doc.status or "").strip()
	prev_status = ((getattr(before, "status", None) if before else None) or "").strip()
	prev_leaf = ((getattr(before, "cheque_leaf", None) if before else None) or "").strip()

	if prev_leaf and prev_leaf != leaf:
		release_leaf_from_guarantee(prev_leaf, doc.name)

	if status in HOLDING_STATUSES:
		if not leaf:
			if status == "Active" and (doc.is_new() or prev_status != "Active"):
				frappe.throw(
					_("Cheque Leaf is required when an Issued Cheque guarantee becomes Active."),
					title=_("Guarantee Document"),
				)
			return
		allocate_leaf_to_guarantee(leaf, doc)
		return

	if status in RELEASE_STATUSES and leaf:
		release_leaf_from_guarantee(leaf, doc)


def validate_issued_cheque_leaf(doc) -> None:
	leaf = (getattr(doc, "cheque_leaf", None) or "").strip()
	if not is_issued_cheque_guarantee(doc):
		if leaf:
			frappe.throw(
				_("Cheque Leaf can only be set for Issued guarantees with Guarantee Type Cheque."),
				title=_("Guarantee Document"),
			)
		return

	status = (doc.status or "").strip()
	before = None if doc.is_new() else doc.get_doc_before_save()
	prev_status = ((getattr(before, "status", None) if before else None) or "").strip()
	becoming_active = status == "Active" and (doc.is_new() or prev_status != "Active")
	if becoming_active and not leaf:
		frappe.throw(
			_("Cheque Leaf is required when an Issued Cheque guarantee becomes Active."),
			title=_("Guarantee Document"),
		)
	if not leaf:
		return
	row = _lock_leaf(leaf)
	if not row:
		frappe.throw(_("Cheque Leaf {0} does not exist.").format(leaf), title=_("Cheque Leaf"))
	if (row.company or "") != (doc.company or ""):
		frappe.throw(
			_("Cheque Leaf must belong to the same Company as this Guarantee Document."),
			title=_("Cheque Leaf"),
		)
	if becoming_active or status in HOLDING_STATUSES:
		# Holding documents may keep an already-allocated leaf; others must be available.
		linked = (row.linked_guarantee_document or "").strip()
		if linked in ("", doc.name or "") and (row.status or "") in (
			"Available",
			STATUS_USED_FOR_GUARANTEE,
		):
			if row.status == "Available":
				assert_leaf_available_for_guarantee(row, doc.name or "")
			return
		assert_leaf_available_for_guarantee(row, doc.name or "")


@frappe.whitelist()
@validate_and_sanitize_search_inputs
def guarantee_cheque_leaf_link_query(
	doctype,
	txt,
	searchfield,
	start,
	page_len,
	filters,
	as_dict=False,
	**kwargs,
):
	"""Link search: Available company cheque leaves not held by PDC or another Guarantee."""
	if isinstance(filters, str):
		filters = frappe.parse_json(filters)
	filters = filters or {}
	company = cstr(filters.get("company", "")).strip()
	if not company:
		return []

	txt = cstr(txt or "").strip()
	start = cint(start)
	page_len = cint(page_len) or 10
	like = f"%{txt}%" if txt else None
	where_extra = ""
	values: dict = {"company": company, "start": start, "page_len": page_len}
	if like is not None:
		where_extra = """ AND (
			cl.name LIKE %(like)s
			OR cl.cheque_number LIKE %(like)s
			OR cl.cheque_book LIKE %(like)s
			OR cl.bank_account LIKE %(like)s
		)"""
		values["like"] = like

	return frappe.db.sql(
		f"""
		SELECT
			cl.name,
			CONCAT_WS(
				' | ',
				NULLIF(TRIM(IFNULL(cl.cheque_number, '')), ''),
				NULLIF(TRIM(IFNULL(cl.status, '')), ''),
				NULLIF(TRIM(IFNULL(cl.bank_account, '')), ''),
				NULLIF(TRIM(IFNULL(cl.cheque_book, '')), '')
			) AS description
		FROM `tabCheque Leaf` cl
		WHERE
			cl.company = %(company)s
			AND cl.status = 'Available'
			AND IFNULL(cl.linked_guarantee_document, '') = ''
			AND IFNULL(cl.linked_post_dated_cheque, '') = ''
			AND IFNULL(cl.reserved_by_pdc, '') = ''
			{where_extra}
		ORDER BY cl.cheque_number ASC
		LIMIT %(start)s, %(page_len)s
		""",
		values,
		as_list=1,
	)
