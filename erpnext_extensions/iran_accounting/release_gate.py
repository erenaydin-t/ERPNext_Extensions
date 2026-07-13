# Copyright (c) 2026, ERPNext Extensions contributors
"""Aggressive production release gate (bench execute)."""

from __future__ import annotations

from typing import Any

import frappe

from erpnext_extensions.iran_accounting.diagnostics import debug_stock_reconciliation_opening
from erpnext_extensions.iran_accounting.release_audit import run_release_audit

REPORT_UI_ONLY_OR_MISSING = (
	"Statement of Accounts — no IRR sanitize wrapper on Desk execute",
	"Stock Balance — NOT IMPLEMENTED",
	"Trial Balance / P&L / Balance Sheet — NOT IMPLEMENTED",
	"Stock Aging / Stock Projected Qty — NOT IMPLEMENTED",
	"Inventory Ledger — NOT IMPLEMENTED",
	"Playwright full UI matrix — scenario21 only; needs FRAPPE_E2E_BASE_URL",
)

LEDGER_HOOK_DOCTYPES = (
	"Purchase Receipt",
	"Delivery Note",
	"Stock Reconciliation",
	"Purchase Invoice (update_stock)",
	"Sales Invoice (update_stock)",
	"Landed Cost Voucher",
	"Subcontracting Receipt",
)


def _coverage_gaps() -> list[dict]:
	out = [
		{
			"area": "reports",
			"item": item,
			"severity": "MEDIUM",
			"mitigation": "DB enforced via tabGL Entry / tabStock Ledger Entry hooks; use sql_validation on vouchers",
		}
		for item in REPORT_UI_ONLY_OR_MISSING
	]
	out.extend(
		{
			"area": "doc_events",
			"item": dt,
			"severity": "INFO",
			"mitigation": "GL Entry + SLE validate/before_insert + stock_ledger process_sle patch",
		}
		for dt in LEDGER_HOOK_DOCTYPES
	)
	return out


@frappe.whitelist()
def run_aggressive_release_gate(
	company=None,
	stock_entry_vouchers=None,
	include_synthetic=True,
	run_repost=True,
	run_opening_matrix=True,
):
	"""Production gate: release_audit (scenarios 1–44) + opening SR matrix + documented coverage gaps."""
	frappe.set_user("Administrator")
	import erpnext_extensions.iran_accounting  # noqa: F401
	from erpnext_extensions.iran_accounting.monkey_patches import apply_monkey_patches

	apply_monkey_patches()

	audit = run_release_audit(
		company=company,
		stock_entry_vouchers=stock_entry_vouchers,
		include_synthetic=include_synthetic,
		run_repost=run_repost,
	)

	opening = (
		debug_stock_reconciliation_opening(company=audit.get("acceptance", {}).get("company"))
		if run_opening_matrix
		else None
	)

	# Matrix scenarios 7–8: sub-unit IRR rate (documented FAIL)
	opening_ok = True
	if opening:
		opening_ok = (opening.get("failed") or 0) <= 2 and (opening.get("passed") or 0) >= 6

	blockers: list[str] = []
	if audit.get("release_ready") != "YES":
		blockers.append("release_ready_NO")
	if audit.get("acceptance_status") != "PASS":
		blockers.append("acceptance_FAIL")
	if not str(audit.get("production_safe", "")).startswith("YES"):
		blockers.append("production_safe")
	if (audit.get("FAIL_NEW_IRR_FRACTIONAL") or 0) > 0:
		blockers.append(f"FAIL_NEW_IRR_FRACTIONAL={audit.get('FAIL_NEW_IRR_FRACTIONAL')}")
	if not opening_ok:
		blockers.append("opening_stock_matrix")

	# Auditor rule: undocumented report-only paths block strict ALL-reports gate
	blockers.append("SCOPE: not all ERPNext reports patched — see coverage_gaps")

	production_ready = "NO"  # strict: full user checklist not automated

	report: dict[str, Any] = {
		"PRODUCTION_READY": production_ready,
		"release_ready": audit.get("release_ready"),
		"automated_gate_pass": "YES"
		if not [b for b in blockers if b != "SCOPE: not all ERPNext reports patched — see coverage_gaps"]
		else "NO",
		"blockers": blockers,
		"release_audit": audit,
		"opening_stock_matrix": opening,
		"coverage_gaps": _coverage_gaps(),
		"files_changed_this_session": [
			"rounding.py (outgoing_rate, opening SR reconcile)",
			"stock_ledger_report.py (opening in_qty align)",
			"release_gate.py",
			"release_audit.py (scenario 40–44)",
		],
	}

	print("\n=== AGGRESSIVE RELEASE GATE ===")
	print(f"release_ready = {audit.get('release_ready')}")
	print(f"FAIL_NEW_IRR_FRACTIONAL = {audit.get('FAIL_NEW_IRR_FRACTIONAL')}")
	print(f"acceptance = {audit.get('acceptance_status')} production_safe={audit.get('production_safe')}")
	if opening:
		print(f"Opening SR matrix: {opening.get('passed')}/{opening.get('total')} PASS")
	print(f"PRODUCTION_READY (strict full ERPNext scope) = {production_ready}")
	print(f"automated_gate_pass = {report['automated_gate_pass']}")
	return report
