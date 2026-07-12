"""Thin wrappers around ERPNext accounting services — no duplicated GL/PLE logic."""

from __future__ import annotations

from typing import Any

import frappe
from frappe.utils import flt

OUTSTANDING_VOUCHERS = frozenset({"Sales Invoice", "Purchase Invoice"})


def cancel_journal_entry_voucher(je_name: str) -> None:
	"""Cancel submitted JE (reverses GL/PLE via ERPNext)."""
	je = frappe.get_doc("Journal Entry", je_name)
	if je.docstatus == 1:
		je.flags.ignore_permissions = True
		je.cancel()
	elif je.docstatus == 0:
		je.flags.ignore_permissions = True
		je.delete()


def refresh_outstanding_for_journal_entry(je_name: str) -> list[dict[str, Any]]:
	"""Always refresh party voucher outstanding after cancelling a JE with invoice references."""
	from erpnext.accounts.utils import update_voucher_outstanding

	updated: list[dict[str, Any]] = []
	seen: set[tuple] = set()
	for row in frappe.get_all(
		"Journal Entry Account",
		filters={"parent": je_name},
		fields=["reference_type", "reference_name", "party_type", "party", "account"],
	):
		ref_type = (row.reference_type or "").strip()
		ref_name = (row.reference_name or "").strip()
		if ref_type not in OUTSTANDING_VOUCHERS or not ref_name:
			continue
		key = (ref_type, ref_name, row.account, row.party_type, row.party)
		if key in seen:
			continue
		seen.add(key)
		before = flt(frappe.db.get_value(ref_type, ref_name, "outstanding_amount"))
		update_voucher_outstanding(ref_type, ref_name, row.account, row.party_type, row.party)
		after = flt(frappe.db.get_value(ref_type, ref_name, "outstanding_amount"))
		updated.append(
			{
				"voucher_type": ref_type,
				"voucher_no": ref_name,
				"outstanding_before": before,
				"outstanding_after": after,
			}
		)
	return updated


def journal_entry_impact_snapshot(je_name: str) -> dict[str, Any]:
	"""Read-only counts + outstanding preview for UI (dry-run)."""
	gl_count = frappe.db.count("GL Entry", {"voucher_no": je_name, "is_cancelled": 0})
	ple_count = frappe.db.count("Payment Ledger Entry", {"voucher_no": je_name, "delinked": 0})
	outstanding_effects: list[dict[str, Any]] = []
	for row in frappe.get_all(
		"Journal Entry Account",
		filters={"parent": je_name},
		fields=[
			"reference_type",
			"reference_name",
			"debit_in_account_currency",
			"credit_in_account_currency",
		],
	):
		ref_type = (row.reference_type or "").strip()
		ref_name = (row.reference_name or "").strip()
		if ref_type not in OUTSTANDING_VOUCHERS or not ref_name:
			continue
		current = flt(frappe.db.get_value(ref_type, ref_name, "outstanding_amount"))
		# Cancelling JE reverses its effect on party/outstanding (register lines credit party/AP).
		delta = flt(row.credit_in_account_currency) - flt(row.debit_in_account_currency)
		after_est = current + delta
		outstanding_effects.append(
			{
				"voucher_type": ref_type,
				"voucher_no": ref_name,
				"outstanding_current": current,
				"outstanding_after_rollback": after_est,
				"outstanding_unchanged": abs(delta) < 1e-9,
			}
		)
	if not outstanding_effects:
		outstanding_effects.append(
			{
				"voucher_type": None,
				"voucher_no": None,
				"outstanding_current": None,
				"outstanding_after_rollback": None,
				"outstanding_unchanged": True,
				"note": "No invoice outstanding affected by this Journal Entry.",
			}
		)
	return {
		"journal_entry": je_name,
		"gl_entry_count": gl_count,
		"payment_ledger_entry_count": ple_count,
		"outstanding_effects": outstanding_effects,
	}


def rollback_journal_reference_row(row_name: str | None) -> None:
	if row_name:
		frappe.delete_doc("PDC Journal Reference", row_name, force=1, ignore_permissions=True)


def cancel_exchange_gain_loss_for_pair(
	parent_doctype: str, parent_name: str, referenced_doctype: str, referenced_name: str
) -> None:
	from erpnext.accounts.utils import cancel_exchange_gain_loss_journal

	parent = frappe.get_doc(parent_doctype, parent_name)
	cancel_exchange_gain_loss_journal(parent, referenced_doctype, referenced_name)
