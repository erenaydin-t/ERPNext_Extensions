# Copyright (c) 2026, ERPNext Extensions contributors
"""Release orphaned Cheque Leaf reservations whose Draft/PDC owner no longer exists.

v4.7.1 — safe, idempotent, non-accounting cleanup.

A Reserved leaf may be released ONLY when:
- status is exactly Reserved
- reserved_by_pdc is non-empty
- that Post Dated Cheque does not exist
- linked_post_dated_cheque is empty
- linked_guarantee_document is empty (when column exists)
- not Used / Void / Used for Guarantee
"""

from __future__ import annotations

from typing import Any

import frappe
from frappe.utils import cstr


def _has_guarantee_columns() -> bool:
	try:
		return bool(frappe.db.has_column("Cheque Leaf", "linked_guarantee_document"))
	except Exception:
		return False


def find_orphaned_reserved_leaf_candidates() -> list[dict[str, Any]]:
	"""Return Reserved leaves whose reserved_by_pdc PDC is missing (candidates only)."""
	if not frappe.db.exists("DocType", "Cheque Leaf"):
		return []
	guarantee_cols = ""
	if _has_guarantee_columns():
		guarantee_cols = ", linked_guarantee_document, guarantee_allocated_on"
	return frappe.db.sql(
		f"""
		SELECT
			cl.name,
			cl.status,
			cl.reserved_by_pdc,
			cl.reserved_on,
			cl.linked_post_dated_cheque,
			cl.used_on,
			cl.company,
			cl.cheque_book,
			cl.cheque_number
			{guarantee_cols}
		FROM `tabCheque Leaf` cl
		WHERE cl.status = 'Reserved'
			AND IFNULL(cl.reserved_by_pdc, '') != ''
			AND NOT EXISTS (
				SELECT 1 FROM `tabPost Dated Cheque` p
				WHERE p.name = cl.reserved_by_pdc
			)
		ORDER BY cl.name
		""",
		as_dict=True,
	)


def classify_orphan_leaf_candidate(row: dict[str, Any]) -> tuple[str, str]:
	"""Return (action, reason) where action is ``release`` or ``skip``."""
	status = cstr(row.get("status") or "").strip()
	reserved_by = cstr(row.get("reserved_by_pdc") or "").strip()
	linked_pdc = cstr(row.get("linked_post_dated_cheque") or "").strip()
	linked_gd = cstr(row.get("linked_guarantee_document") or "").strip()

	if status != "Reserved":
		return "skip", f"status_is_{status or 'empty'}"
	if not reserved_by:
		return "skip", "empty_reserved_by_pdc"
	if frappe.db.exists("Post Dated Cheque", reserved_by):
		return "skip", "pdc_still_exists"
	if linked_pdc:
		return "skip", "has_linked_post_dated_cheque"
	if linked_gd:
		return "skip", "has_linked_guarantee_document"
	if status in ("Used", "Void", "Used for Guarantee"):
		return "skip", f"status_is_{status}"
	return "release", "missing_pdc_owner"


def release_orphaned_reserved_leaf(leaf_name: str) -> dict[str, Any]:
	"""Attempt one safe orphan release. Returns result dict; never raises for skip cases."""
	from erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque import (
		_pdc_get_cheque_leaf_row_for_update,
	)

	row = _pdc_get_cheque_leaf_row_for_update(leaf_name)
	if not row:
		return {"name": leaf_name, "action": "skip", "reason": "leaf_missing"}

	payload = dict(row)
	action, reason = classify_orphan_leaf_candidate(payload)
	if action != "release":
		return {"name": leaf_name, "action": "skip", "reason": reason}

	frappe.db.set_value(
		"Cheque Leaf",
		leaf_name,
		{"status": "Available", "reserved_by_pdc": None, "reserved_on": None},
		update_modified=False,
	)
	return {
		"name": leaf_name,
		"action": "release",
		"reason": reason,
		"previous_reserved_by_pdc": cstr(row.reserved_by_pdc or ""),
	}


def repair_orphaned_pdc_cheque_leaf_reservations() -> dict[str, Any]:
	"""Scan and safely release proven orphan Reserved leaves. Idempotent."""
	released: list[dict[str, Any]] = []
	skipped: list[dict[str, Any]] = []

	for candidate in find_orphaned_reserved_leaf_candidates():
		result = release_orphaned_reserved_leaf(candidate["name"])
		if result.get("action") == "release":
			released.append(result)
			frappe.logger("erpnext_extensions.cheque_management").info(
				"v4.7.1 orphan leaf released: %s (was reserved_by_pdc=%s)",
				result.get("name"),
				result.get("previous_reserved_by_pdc"),
			)
		else:
			skipped.append(result)
			frappe.logger("erpnext_extensions.cheque_management").warning(
				"v4.7.1 orphan leaf skipped: %s reason=%s",
				result.get("name"),
				result.get("reason"),
			)

	return {
		"candidates": len(released) + len(skipped),
		"released": released,
		"skipped": skipped,
		"released_count": len(released),
		"skipped_count": len(skipped),
	}


def execute():
	if not frappe.db.exists("DocType", "Cheque Leaf"):
		return
	result = repair_orphaned_pdc_cheque_leaf_reservations()
	frappe.logger("erpnext_extensions.cheque_management").info(
		"v4.7.1 orphan leaf repair complete: released=%s skipped=%s",
		result.get("released_count"),
		result.get("skipped_count"),
	)
