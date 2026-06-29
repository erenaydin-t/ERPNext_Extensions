# Copyright (c) 2026, ERPNext Extensions contributors
"""Production acceptance runner for iran_accounting (bench execute)."""

from __future__ import annotations

from typing import Any

import frappe
from frappe.utils import cint

from erpnext_extensions.iran_accounting.acceptance_scenarios import (
	AcceptanceContext,
	run_real_stock_entries,
	run_scenarios,
	scenario_row,
)
from erpnext_extensions.iran_accounting.diagnostics import (
	check_company_fractional_irr,
	check_fractional_for_vouchers,
)
from erpnext_extensions.iran_accounting.rounding import get_company_currency, get_currency_precision


def _row(area: str, voucher: str, status: str, manual_required: bool = False, **extra) -> dict:
	row: dict[str, Any] = {"area": area, "voucher": voucher, "status": status}
	if manual_required:
		row["manual_required"] = True
	row.update(extra)
	return row


def _check_irr_settings(company: str) -> tuple[list[dict], dict]:
	"""IRR settings check (used by acceptance tests and scenario 1 logic)."""
	import json

	cur = get_company_currency(company)
	sys_prec = frappe.db.get_single_value("System Settings", "currency_precision")
	use_nf = frappe.db.get_single_value("System Settings", "use_number_format_from_currency")
	irr_nf = frappe.db.get_value("Currency", "IRR", "number_format")
	resolved = get_currency_precision("IRR")
	info = {
		"company_currency": cur,
		"system_currency_precision": sys_prec,
		"use_number_format_from_currency": use_nf,
		"irr_number_format": irr_nf,
		"resolved_irr_precision": resolved,
	}
	ok = cur == "IRR" and resolved == 0
	row = scenario_row(1, "settings", company, "PASS" if ok else "FAIL", evidence=json.dumps(info, default=str))
	return [row], info


def _parse_list(value) -> list | None:
	if value is None:
		return None
	if isinstance(value, str):
		return frappe.parse_json(value)
	return list(value)


def _bootstrap():
	from erpnext_extensions.iran_accounting import e2e_bootstrap as b

	return b


def _print_table(rows: list[dict]) -> None:
	headers = (
		"scenario_no",
		"area",
		"voucher",
		"status",
		"db_ok",
		"report_ok",
		"export_ok",
		"ui_ok",
		"db_gl_ok",
		"db_sle_ok",
		"db_stock_entry_ok",
		"preview_ok",
		"repost_ok",
		"ui_api_ok",
		"no_double_ok",
		"no_adjustment_ok",
		"evidence",
	)
	widths = [5, 18, 22, 8, 6, 9, 9, 6, 8, 8, 10, 10, 8, 8, 10, 12, 36]
	line = " | ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
	print(line)
	print("-" * len(line))
	for row in rows:
		print(
			" | ".join(
				str(row.get(h, "")).ljust(widths[i])[: widths[i]] for i, h in enumerate(headers)
			)
		)


def _overall_status(rows: list[dict]) -> str:
	for row in rows:
		if row.get("status") in ("MANUAL_REQUIRED", "SKIP"):
			continue
		if row.get("status") != "PASS":
			return "FAIL"
	return "PASS"


def _production_safe(rows: list[dict], status: str) -> str:
	s39 = next((r for r in rows if r.get("scenario_no") == 39), None)
	if not s39 or s39.get("status") != "PASS":
		return "NO"
	if s39.get("db_ok") is False or s39.get("gl_ok") is False or s39.get("sle_ok") is False:
		return "NO"
	s30 = next((r for r in rows if r.get("scenario_no") == 30), None)
	if not s30 or s30.get("status") != "PASS":
		return "NO"
	if s30.get("db_ok") is False or s30.get("report_ok") is False or s30.get("export_ok") is False:
		return "NO"
	if s30.get("repost_ok") is False:
		return "NO"
	s21 = next((r for r in rows if r.get("scenario_no") == 21), None)
	if not s21 or s21.get("status") != "PASS":
		return "NO"
	for n in range(31, 39):
		s = next((r for r in rows if r.get("scenario_no") == n), None)
		if s and s.get("status") == "FAIL":
			return "NO"
	if status != "PASS":
		return "NO"
	print_manual = any(
		r.get("status") == "MANUAL_REQUIRED"
		or (
			r.get("print_ok") in ("MANUAL_REQUIRED", "MANUAL")
			and r.get("status") == "PASS"
		)
		for r in rows
	)
	if print_manual:
		return "YES except print manual validation"
	return "YES"


def _summarize(rows: list[dict], skipped: list) -> dict:
	implemented = len(rows)
	passed = sum(1 for r in rows if r.get("status") == "PASS")
	skipped_n = sum(1 for r in rows if r.get("status") == "SKIP") + len(skipped)
	manual = sum(1 for r in rows if r.get("status") == "MANUAL_REQUIRED")
	repost_rows = [r for r in rows if r.get("repost_ok") is not None]
	wo_areas = ("Work Order", "MTfM", "Manufacture", "BOM")
	wo_cov = [r for r in rows if any(a in (r.get("area") or "") for a in wo_areas)]
	return {
		"scenarios_implemented": implemented,
		"scenarios_passed": passed,
		"scenarios_skipped": skipped_n,
		"scenarios_manual_required": manual,
		"skipped_detail": skipped,
		"repost_scenarios": len(repost_rows),
		"repost_passed": sum(1 for r in repost_rows if r.get("repost_ok")),
		"work_order_scenarios": len(wo_cov),
		"work_order_passed": sum(1 for r in wo_cov if r.get("status") == "PASS"),
	}


def _print_runbook(company: str, run_repost: bool, result: dict) -> None:
	s = result["summary"]
	print("\n--- Acceptance summary ---")
	print(f"1. Scenarios implemented: {s['scenarios_implemented']}")
	print(f"2. Scenarios passed: {s['scenarios_passed']}")
	print(f"3. Scenarios skipped: {s['scenarios_skipped']}")
	for row in result["rows"]:
		if row.get("status") == "SKIP":
			print(f"   SKIP #{row.get('scenario_no')} {row.get('area')}: {row.get('evidence')}")
	print(
		f"4. Repost Item Valuation coverage: {s.get('repost_passed', 0)}/{s.get('repost_scenarios', 0)} "
		f"(run_repost={run_repost})"
	)
	print(
		f"5. Work Order / BOM / MTfM / Manufacture: {s.get('work_order_passed', 0)}/"
		f"{s.get('work_order_scenarios', 0)} passed"
	)
	print(
		'6. Production/staging command:\n'
		f'   bench --site <site> execute erpnext_extensions.iran_accounting.acceptance.run '
		f'--kwargs \'{{"company":"{company}","include_synthetic":True,"run_repost":True,'
		f'"scenario_count":39,"stock_entry_vouchers":["MAT-STE-2026-00102"]}}\''
	)
	print(f"7. Production safe: {result['production_safe']}")


@frappe.whitelist()
def run(
	company=None,
	stock_entry_vouchers=None,
	include_synthetic=True,
	run_repost=True,
	scenario_count=20,
):
	"""Production acceptance for iran_accounting.

	bench execute kwargs must use Python literals (True/False), not JSON true/false.
	"""
	frappe.set_user("Administrator")
	import erpnext_extensions.iran_accounting  # noqa: F401 — apply patches
	include_synthetic = bool(cint(include_synthetic)) if isinstance(include_synthetic, (int, str)) else bool(include_synthetic)
	run_repost = bool(cint(run_repost)) if isinstance(run_repost, (int, str)) else bool(run_repost)
	scenario_count = int(scenario_count or 20)

	b = _bootstrap()
	company = b.get_irr_company(company or None)
	b.enable_perpetual_inventory(company)
	try:
		b.ensure_foreign_currency_acceptance_masters(company)
	except Exception as exc:
		frappe.log_error(title="iran_accounting FC bootstrap", message=str(exc))
	from erpnext_extensions.iran_accounting.monkey_patches import apply_monkey_patches

	apply_monkey_patches()
	warehouse = b.get_warehouse(company)
	to_wh = b.get_second_warehouse(company, warehouse)

	ctx = AcceptanceContext(
		company=company,
		warehouse=warehouse,
		to_wh=to_wh,
		run_repost=run_repost,
		include_synthetic=include_synthetic,
		b=b,
	)

	rows: list[dict] = []
	rows.extend(run_scenarios(ctx, min(scenario_count, 44)))

	vouchers = _parse_list(stock_entry_vouchers)
	if vouchers is None:
		vouchers = ["MAT-STE-2026-00005", "PO-JOB00049-1"]
	vouchers = [v for v in vouchers if v]
	if vouchers:
		rows.extend(run_real_stock_entries(ctx, vouchers))

	def _doctype_for_name(name: str) -> str | None:
		for dt in (
			"Stock Entry",
			"Stock Reconciliation",
			"Purchase Receipt",
			"Purchase Invoice",
			"Sales Invoice",
			"Delivery Note",
		):
			if frappe.db.exists(dt, name):
				return dt
		return None

	scope_vouchers: list[tuple[str, str]] = []
	for name in list(ctx.refs.values()) + list(vouchers):
		if not name:
			continue
		dt = _doctype_for_name(name)
		if dt:
			scope_vouchers.append((dt, name))
	seen: set[tuple[str, str]] = set()
	scope_vouchers = [x for x in scope_vouchers if x not in seen and not seen.add(x)]

	if scope_vouchers:
		frac = check_fractional_for_vouchers(company, scope_vouchers)
		evidence = (
			f"scoped={len(scope_vouchers)} "
			f"fail_new_irr={len(frac.get('fail_new_irr_fractional') or [])} "
			f"fc_decimal_ok={len(frac.get('allowed_fc_decimal') or [])} "
			f"sle={len(frac.get('fractional_sle') or [])} "
			f"ste={len(frac.get('fractional_stock_entry') or [])}"
		)
	else:
		frac = check_company_fractional_irr(company=company, limit=30)
		evidence = f"scan gl={len(frac.get('fractional_gl', []))}"
	rows.append(
		scenario_row(
			999,
			"GL Entry",
			"company-scan",
			frac.get("status", "FAIL"),
			gl_ok=not frac.get("fail_new_irr_fractional", frac.get("fractional_gl")),
			sle_ok=not frac.get("fractional_sle"),
			totals_ok=not frac.get("fractional_stock_entry"),
			evidence=evidence,
		)
	)

	status = _overall_status(rows)
	summary = _summarize(rows, ctx.skipped)
	result: dict[str, Any] = {
		"status": status,
		"company": company,
		"include_synthetic": include_synthetic,
		"run_repost": run_repost,
		"scenario_count": scenario_count,
		"stock_entry_vouchers": vouchers,
		"summary": summary,
		"rows": rows,
		"production_safe": _production_safe(rows, status),
	}
	_print_table(rows)
	print(f"\nFINAL: {status}")
	print(f"Production safe: {result['production_safe']}")
	print(f"Summary: {summary}")
	_print_runbook(company, run_repost, result)
	return result
