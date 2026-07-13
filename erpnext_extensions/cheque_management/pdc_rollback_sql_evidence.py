"""SQL / accounting snapshots for PDC rollback release evidence."""

from __future__ import annotations

import json
from typing import Any

import frappe
from frappe.utils import flt


def accounting_snapshot_for_pdc(pdc_name: str) -> dict[str, Any]:
	"""Point-in-time counts and key rows for release SQL verification."""
	pdc = frappe.db.get_value(
		"Post Dated Cheque",
		pdc_name,
		[
			"name",
			"workflow_state",
			"cheque_status",
			"docstatus",
			"cheque_direction",
			"cheque_leaf",
			"company",
		],
		as_dict=True,
	)
	if not pdc:
		frappe.throw(f"Post Dated Cheque {pdc_name} not found")

	refs = frappe.get_all(
		"PDC Journal Reference",
		filters={"parent": pdc_name, "parenttype": "Post Dated Cheque"},
		fields=["name", "journal_entry", "pdc_transition_key", "purpose"],
	)
	je_names = sorted({r.journal_entry for r in refs if r.journal_entry})

	journal_entries = []
	for je in je_names:
		journal_entries.append(
			{
				"name": je,
				"docstatus": frappe.db.get_value("Journal Entry", je, "docstatus"),
			}
		)

	jea_count = 0
	gl_count = 0
	ple_count = 0
	for je in je_names:
		jea_count += frappe.db.count("Journal Entry Account", {"parent": je})
		gl_count += frappe.db.count("GL Entry", {"voucher_no": je, "is_cancelled": 0})
		ple_count += frappe.db.count("Payment Ledger Entry", {"voucher_no": je, "delinked": 0})

	outstanding: list[dict[str, Any]] = []
	for row in frappe.get_all(
		"PDC Allocation",
		filters={"parent": pdc_name, "parenttype": "Post Dated Cheque"},
		fields=["reference_doctype", "reference_name", "amount"],
	):
		ref_type = (row.reference_doctype or "").strip()
		ref_name = (row.reference_name or "").strip()
		if ref_type in ("Sales Invoice", "Purchase Invoice") and ref_name:
			outstanding.append(
				{
					"voucher_type": ref_type,
					"voucher_no": ref_name,
					"outstanding_amount": flt(frappe.db.get_value(ref_type, ref_name, "outstanding_amount")),
					"allocated_amount": flt(row.amount),
				}
			)

	leaf = None
	if pdc.cheque_leaf:
		leaf = frappe.db.get_value(
			"Cheque Leaf",
			pdc.cheque_leaf,
			["name", "status", "linked_post_dated_cheque", "reserved_by_pdc"],
			as_dict=True,
		)

	rollback_log_count = frappe.db.count("PDC Workflow Rollback Log", {"parent": pdc_name})
	comment_count = frappe.db.count(
		"Comment",
		{
			"reference_doctype": "Post Dated Cheque",
			"reference_name": pdc_name,
			"comment_type": "Workflow",
		},
	)

	return {
		"pdc": pdc,
		"journal_entries": journal_entries,
		"journal_entry_account_count": jea_count,
		"gl_entry_count": gl_count,
		"payment_ledger_entry_count": ple_count,
		"pdc_journal_references": refs,
		"outstanding": outstanding,
		"cheque_leaf": leaf,
		"rollback_log_count": rollback_log_count,
		"workflow_comment_count": comment_count,
	}


def snapshot_rollback_scenario(pdc_name: str, target_state: str, reason: str) -> dict[str, Any]:
	"""Before / after snapshot for one rollback (dry-run plan + execute)."""
	from erpnext_extensions.cheque_management.accounting_rollback.pdc.plan import (
		build_pdc_rollback_plan,
	)
	from erpnext_extensions.cheque_management.pdc_workflow_rollback import (
		get_pdc_workflow_rollback_preview,
		rollback_workflow_state,
	)

	before = accounting_snapshot_for_pdc(pdc_name)
	preview = get_pdc_workflow_rollback_preview(pdc_name, target_state)
	plan = build_pdc_rollback_plan(frappe.get_doc("Post Dated Cheque", pdc_name), target_state, reason=reason)
	result = rollback_workflow_state(pdc_name, target_state, reason)
	after = accounting_snapshot_for_pdc(pdc_name)
	return {
		"scenario": {
			"pdc_name": pdc_name,
			"target_state": target_state,
			"reason": reason,
		},
		"plan_transitions": preview.get("transitions_to_undo")
		or plan.to_api_dict().get("transitions_to_undo"),
		"before": before,
		"after": after,
		"result": result,
	}


def generate_release_sql_evidence() -> dict[str, Any]:
	"""Collect before/after SQL snapshots via integration harness (no E2E prep)."""
	from erpnext_extensions.cheque_management.tests.test_pdc_workflow_rollback_lifecycle_integration import (
		run_integration_sql_evidence,
	)

	return run_integration_sql_evidence()


def write_release_sql_evidence_file() -> str:
	"""Bench execute: write JSON evidence under cheque_management/release_reports/."""
	import os
	from pathlib import Path

	data = generate_release_sql_evidence()
	app_root = Path(frappe.get_app_path("erpnext_extensions"))
	out_dir = app_root / "cheque_management" / "release_reports"
	out_dir.mkdir(parents=True, exist_ok=True)
	out_path = out_dir / "pdc_workflow_rollback_sql_evidence.json"
	out_path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
	return str(out_path)
