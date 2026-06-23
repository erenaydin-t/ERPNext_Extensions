# Copyright (c) 2026, ERPNext Extensions contributors
"""One-shot release audit wrapper (bench execute)."""

from __future__ import annotations

import frappe

from erpnext_extensions.iran_accounting.acceptance import run as run_acceptance
from erpnext_extensions.iran_accounting.diagnostics import (
	check_stock_value_residual,
	classify_company_fractional_irr,
	repair_company_fractional_irr,
)


@frappe.whitelist()
def run_release_audit(
	company=None,
	stock_entry_vouchers=None,
	include_synthetic=True,
	run_repost=True,
):
	"""Run acceptance + blocker voucher residual check; return structured release report."""
	vouchers = stock_entry_vouchers or ["MAT-STE-2026-00102"]
	blocker = vouchers[0]
	acceptance = run_acceptance(
		company=company,
		stock_entry_vouchers=vouchers,
		include_synthetic=include_synthetic,
		run_repost=run_repost,
		scenario_count=39,
	)
	residual = check_stock_value_residual(blocker, acceptance.get("company"))
	repair_company_fractional_irr(company=acceptance.get("company") or company)
	rows = acceptance.get("rows") or []
	gates = {
		"s21_mtfm": next((r for r in rows if r.get("scenario_no") == 21), {}),
		"s30_sle_strict": next((r for r in rows if r.get("scenario_no") == 30), {}),
		"s39_residual": next((r for r in rows if r.get("scenario_no") == 39), {}),
		"s31_38_fc": [r for r in rows if 31 <= (r.get("scenario_no") or 0) <= 38],
		"s999_scan": next((r for r in rows if r.get("scenario_no") == 999), {}),
	}
	fc_fail = [r for r in gates["s31_38_fc"] if r.get("status") == "FAIL"]
	company_scan = classify_company_fractional_irr(company=acceptance.get("company") or company)
	fail_new_count = (company_scan.get("counts") or {}).get("fail_new_irr_fractional", 0)
	release_ready = (
		acceptance.get("status") == "PASS"
		and acceptance.get("production_safe", "").startswith("YES")
		and residual.get("status") == "PASS"
		and gates["s21_mtfm"].get("status") == "PASS"
		and gates["s30_sle_strict"].get("status") == "PASS"
		and gates["s39_residual"].get("status") == "PASS"
		and not fc_fail
		and gates["s999_scan"].get("status") == "PASS"
		and fail_new_count == 0
	)
	return {
		"release_ready": "YES" if release_ready else "NO",
		"company_fractional_scan": company_scan,
		"FAIL_NEW_IRR_FRACTIONAL": fail_new_count,
		"LEGACY_REPOST_REQUIRED": (company_scan.get("counts") or {}).get("legacy_repost_required", 0),
		"ALLOWED_FC_DECIMAL": (company_scan.get("counts") or {}).get("allowed_fc_decimal", 0),
		"acceptance_status": acceptance.get("status"),
		"production_safe": acceptance.get("production_safe"),
		"blocker_residual": residual,
		"gates": gates,
		"summary": acceptance.get("summary"),
		"acceptance": acceptance,
	}
