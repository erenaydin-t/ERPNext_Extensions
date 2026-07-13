# Copyright (c) 2026, ERPNext Extensions contributors
"""Safe unlink of Cheque Opening Import Item → PDC links, then delete PDC (no accounting changes)."""

from __future__ import annotations

import json
from typing import Any

import frappe
from frappe import _
from frappe.utils import cint, now_datetime


class PDCImportCleanupError(frappe.ValidationError):
	"""Blocked delete — accounting or policy."""


def audit_pdc_import_cleanup_safety(pdc_name: str) -> dict[str, Any]:
	"""Read-only safety report (accounting + import item links)."""
	pdc_name = (pdc_name or "").strip()
	if not pdc_name or not frappe.db.exists("Post Dated Cheque", pdc_name):
		frappe.throw(_("Post Dated Cheque {0} does not exist.").format(pdc_name))

	pdc = frappe.db.get_value(
		"Post Dated Cheque",
		pdc_name,
		["name", "docstatus", "workflow_state", "cheque_no", "cheque_amount", "cheque_leaf"],
		as_dict=True,
	)

	coi_items = _find_cheque_opening_import_items(pdc_name)
	journal_refs = frappe.get_all(
		"PDC Journal Reference",
		filters={"parent": pdc_name, "parenttype": "Post Dated Cheque"},
		fields=["name", "journal_entry"],
	)
	je_names = _linked_journal_entries(pdc_name)
	gl_count = _gl_entry_count_for_pdc(pdc_name, je_names)
	ple_count = _payment_ledger_count_for_pdc(pdc_name, je_names)

	blockers = _accounting_blockers(pdc_name, journal_refs, je_names, gl_count, ple_count)
	safe = not blockers

	return {
		"pdc": pdc,
		"cheque_opening_import_items": coi_items,
		"journal_references": journal_refs,
		"journal_entries": sorted(je_names),
		"gl_entry_count": gl_count,
		"payment_ledger_entry_count": ple_count,
		"blockers": blockers,
		"safe_to_unlink_and_delete": safe,
		"primary_link_blocker": bool(coi_items),
	}


def unlink_opening_import_and_delete_pdc(
	pdc_name: str, reason: str = "", *, permission_check: bool = True
) -> dict[str, Any]:
	"""Unlink COI item PDC links, then cancel (if submitted) and delete PDC."""
	if permission_check:
		_require_administrator()
	pdc_name = (pdc_name or "").strip()
	reason = (reason or "").strip()
	if not reason:
		frappe.throw(_("Reason is required for PDC import cleanup."))

	report = audit_pdc_import_cleanup_safety(pdc_name)
	if not report["safe_to_unlink_and_delete"]:
		raise PDCImportCleanupError(
			_("Cannot delete PDC {0}. Blockers:\n{1}").format(pdc_name, "\n".join(report["blockers"]))
		)

	if not report["cheque_opening_import_items"]:
		raise PDCImportCleanupError(_("No Cheque Opening Import Item links this Post Dated Cheque."))

	unlinked_rows: list[dict[str, Any]] = []
	for row in report["cheque_opening_import_items"]:
		frappe.db.set_value(
			"Cheque Opening Import Item",
			row.name,
			{"imported_pdc": None, "post_dated_cheque": None},
			update_modified=True,
		)
		unlinked_rows.append(
			{
				"item_name": row.name,
				"parent": row.parent,
				"row_number": row.row_number,
				"row_status_unchanged": row.row_status,
			}
		)

	_clear_cheque_leaf_links_non_accounting(pdc_name)

	docstatus = cint(report["pdc"]["docstatus"])
	if docstatus == 1:
		from erpnext_extensions.cheque_management.pdc_direct_cancel_policy import (
			pdc_internal_direct_cancel,
		)

		with pdc_internal_direct_cancel(flag="in_cheque_opening_import_delete"):
			frappe.get_doc("Post Dated Cheque", pdc_name).cancel()
	elif docstatus == 2:
		pass
	elif docstatus != 0:
		frappe.throw(_("Unexpected docstatus {0} for {1}.").format(docstatus, pdc_name))

	frappe.delete_doc("Post Dated Cheque", pdc_name)

	log_payload = {
		"event": "PDC deleted after import unlink",
		"pdc_name": pdc_name,
		"reason": reason,
		"user": frappe.session.user,
		"timestamp": str(now_datetime()),
		"unlinked_import_items": unlinked_rows,
		"cheque_opening_import_parents": sorted({r["parent"] for r in unlinked_rows}),
	}
	_log_cleanup(log_payload)

	frappe.db.commit()

	return {
		"ok": True,
		"pdc_name": pdc_name,
		"unlinked_import_items": unlinked_rows,
		"audit": report,
	}


def _require_administrator() -> None:
	if frappe.session.user == "Administrator":
		return
	frappe.throw(
		_("Only Administrator can delete imported PDC records."),
		frappe.PermissionError,
	)


def _require_system_manager() -> None:
	"""Deprecated alias — bench scripts should use Administrator."""
	_require_administrator()


def _find_cheque_opening_import_items(pdc_name: str) -> list[dict[str, Any]]:
	seen: set[str] = set()
	out: list[dict[str, Any]] = []
	for filters in ({"imported_pdc": pdc_name}, {"post_dated_cheque": pdc_name}):
		for row in frappe.get_all(
			"Cheque Opening Import Item",
			filters=filters,
			fields=["name", "parent", "row_number", "row_status", "imported_pdc", "post_dated_cheque"],
		):
			if row.name in seen:
				continue
			seen.add(row.name)
			out.append(row)
	return out


def _linked_journal_entries(pdc_name: str) -> set[str]:
	jes: set[str] = set()
	for row in frappe.get_all(
		"PDC Journal Reference",
		filters={"parent": pdc_name, "parenttype": "Post Dated Cheque"},
		fields=["journal_entry"],
	):
		if row.journal_entry:
			jes.add(row.journal_entry)
	for name in frappe.get_all("Journal Entry", filters={"cheque_no": pdc_name}, pluck="name") or []:
		jes.add(name)
	return jes


def _gl_entry_count_for_pdc(pdc_name: str, je_names: set[str]) -> int:
	total = frappe.db.count(
		"GL Entry",
		{"voucher_type": "Post Dated Cheque", "voucher_no": pdc_name, "is_cancelled": 0},
	)
	for je in je_names:
		total += frappe.db.count(
			"GL Entry",
			{"voucher_type": "Journal Entry", "voucher_no": je, "is_cancelled": 0},
		)
	return total


def _payment_ledger_count_for_pdc(pdc_name: str, je_names: set[str]) -> int:
	if not frappe.db.table_exists("Payment Ledger Entry"):
		return 0
	total = frappe.db.count(
		"Payment Ledger Entry",
		{"voucher_type": "Post Dated Cheque", "voucher_no": pdc_name},
	)
	for je in je_names:
		total += frappe.db.count(
			"Payment Ledger Entry",
			{"voucher_type": "Journal Entry", "voucher_no": je},
		)
	return total


def _accounting_blockers(
	pdc_name: str,
	journal_refs: list[dict],
	je_names: set[str],
	gl_count: int,
	ple_count: int,
) -> list[str]:
	blockers: list[str] = []
	if journal_refs:
		blockers.append(
			_("PDC Journal Reference exists on this cheque ({0} row(s)).").format(len(journal_refs))
		)
	if je_names:
		blockers.append(_("Journal Entry linked ({0}).").format(", ".join(sorted(je_names))))
	if gl_count:
		blockers.append(_("GL Entry exists ({0} row(s)).").format(gl_count))
	if ple_count:
		blockers.append(_("Payment Ledger Entry exists ({0} row(s)).").format(ple_count))
	return blockers


def _clear_cheque_leaf_links_non_accounting(pdc_name: str) -> None:
	"""Release payable leaf reservation so delete_doc can succeed (not accounting)."""
	leaf_name = frappe.db.get_value("Post Dated Cheque", pdc_name, "cheque_leaf")
	if not leaf_name:
		return
	leaf = frappe.db.get_value(
		"Cheque Leaf",
		leaf_name,
		["name", "status", "linked_post_dated_cheque", "reserved_by_pdc"],
		as_dict=True,
	)
	if not leaf:
		return
	updates: dict[str, Any] = {}
	if leaf.linked_post_dated_cheque == pdc_name:
		updates["linked_post_dated_cheque"] = None
	if leaf.reserved_by_pdc == pdc_name:
		updates["reserved_by_pdc"] = None
		if leaf.status == "Reserved":
			updates["status"] = "Available"
	if updates:
		frappe.db.set_value("Cheque Leaf", leaf_name, updates, update_modified=False)


def _log_cleanup(payload: dict[str, Any]) -> None:
	frappe.log_error(
		title="PDC deleted after import unlink",
		message=json.dumps(payload, indent=2, default=str),
	)
