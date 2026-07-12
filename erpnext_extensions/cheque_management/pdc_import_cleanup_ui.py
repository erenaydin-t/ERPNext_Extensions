# Copyright (c) 2026, ERPNext Extensions contributors
"""Desk API for safe deletion of opening-import Post Dated Cheques (Administrator only)."""

from __future__ import annotations

from typing import Any

import frappe
from frappe import _

from erpnext_extensions.cheque_management.utils.pdc_import_cleanup import (
	PDCImportCleanupError,
	audit_pdc_import_cleanup_safety,
	unlink_opening_import_and_delete_pdc,
)


def _require_administrator() -> None:
	if frappe.session.user == "Administrator":
		return
	frappe.throw(
		_("Only Administrator can delete imported PDC records."),
		frappe.PermissionError,
	)


def _user_may_delete_imported_pdc_ui() -> bool:
	return frappe.session.user == "Administrator"


@frappe.whitelist()
def user_may_delete_imported_pdc_ui() -> bool:
	"""Desk: whether Delete Imported PDC actions may be shown."""
	return _user_may_delete_imported_pdc_ui()


@frappe.whitelist()
def preview_delete_imported_pdc(pdc_name: str) -> dict[str, Any]:
	"""Safety audit + display fields for confirmation dialog."""
	_require_administrator()
	pdc_name = (pdc_name or "").strip()
	if not pdc_name:
		frappe.throw(_("Post Dated Cheque is required."))

	audit = audit_pdc_import_cleanup_safety(pdc_name)
	coi_items = audit.get("cheque_opening_import_items") or []

	if not coi_items:
		audit["blockers"] = list(audit.get("blockers") or []) + [
			_("No Cheque Opening Import Item links this Post Dated Cheque.")
		]
		audit["safe_to_unlink_and_delete"] = False

	pdc = frappe.db.get_value(
		"Post Dated Cheque",
		pdc_name,
		["name", "docstatus", "workflow_state", "cheque_no", "cheque_amount", "opening_import"],
		as_dict=True,
	)

	rows_for_ui = []
	for item in coi_items:
		rows_for_ui.append(
			{
				"cheque_opening_import": item.parent,
				"item_name": item.name,
				"row_number": item.row_number,
				"row_status": item.row_status,
			}
		)

	return {
		"allowed": bool(audit.get("safe_to_unlink_and_delete")) and bool(coi_items),
		"pdc_name": pdc_name,
		"pdc": pdc,
		"cheque_opening_import": (coi_items[0].parent if coi_items else None)
		or (pdc or {}).get("opening_import"),
		"row_number": coi_items[0].row_number if coi_items else None,
		"coi_items": rows_for_ui,
		"audit_summary": {
			"journal_references_count": len(audit.get("journal_references") or []),
			"journal_entries_count": len(audit.get("journal_entries") or []),
			"gl_entry_count": audit.get("gl_entry_count") or 0,
			"payment_ledger_entry_count": audit.get("payment_ledger_entry_count") or 0,
			"blockers_count": len(audit.get("blockers") or []),
		},
		"blockers": audit.get("blockers") or [],
		"audit": audit,
	}


@frappe.whitelist()
def delete_imported_pdc_from_ui(pdc_name: str, reason: str) -> dict[str, Any]:
	"""Delete imported PDC after audit; Administrator only."""
	_require_administrator()
	pdc_name = (pdc_name or "").strip()
	reason = (reason or "").strip()
	if not reason:
		frappe.throw(_("Reason is required."))

	preview = preview_delete_imported_pdc(pdc_name)
	if not preview.get("allowed"):
		raise PDCImportCleanupError(
			_("Cannot delete imported PDC. Blockers:\n{0}").format("\n".join(preview.get("blockers") or []))
		)

	try:
		result = unlink_opening_import_and_delete_pdc(pdc_name, reason, permission_check=False)
	except PDCImportCleanupError:
		raise
	_add_cheque_opening_import_timeline_comments(result.get("unlinked_import_items") or [], pdc_name, reason)
	return {
		"ok": True,
		"message": _("Imported PDC deleted successfully."),
		**result,
	}


def _add_cheque_opening_import_timeline_comments(
	unlinked_items: list[dict[str, Any]], pdc_name: str, reason: str
) -> None:
	user = frappe.session.user
	text = _("Imported PDC {0} was deleted by {1}. Reason: {2}").format(pdc_name, user, reason)
	parents = sorted({row.get("parent") for row in unlinked_items if row.get("parent")})
	for parent in parents:
		if not frappe.db.exists("Cheque Opening Import", parent):
			continue
		frappe.get_doc("Cheque Opening Import", parent).add_comment("Info", text)
