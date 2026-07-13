# Copyright (c) 2026, ERPNext Extensions contributors
"""Bulk Repost Item Valuation for Stock Reconciliation affected by IRR balance-value bug.

Uses ERPNext ``Repost Item Valuation`` (Transaction-based) only — never writes SLE fields directly.
"""

from __future__ import annotations

import json
from typing import Any

import frappe
from frappe.utils import cint, flt, getdate

from erpnext_extensions.iran_accounting.domain.currency import (
	get_company_currency,
	is_irr_company,
	round_currency,
)
from erpnext_extensions.iran_accounting.domain.stock_reconciliation_sync import (
	_prior_warehouse_sle_before,
)

BALANCE_TOLERANCE_IRR = 1


def resolve_company(company: str) -> str:
	"""Resolve Company name from ``name`` or ``company_name`` (e.g. Persian label)."""
	company = (company or "").strip()
	if not company:
		frappe.throw("company is required")
	if frappe.db.exists("Company", company):
		return company
	by_label = frappe.db.get_value("Company", {"company_name": company}, "name")
	if by_label:
		return by_label
	frappe.throw(f"Company not found: {company}")


def _submitted_stock_reconciliations(
	company: str,
	from_date: str,
	*,
	voucher_nos: list[str] | None = None,
) -> list[dict]:
	filters: dict[str, Any] = {
		"docstatus": 1,
		"company": company,
		"posting_date": (">=", getdate(from_date)),
	}
	if voucher_nos:
		filters["name"] = ("in", voucher_nos)
	return frappe.get_all(
		"Stock Reconciliation",
		filters=filters,
		fields=["name", "posting_date", "posting_time", "company", "purpose"],
		order_by="posting_date asc, posting_time asc, creation asc",
	)


def sle_balance_issues_for_voucher(voucher_no: str, company: str) -> list[dict]:
	"""Rows where ``stock_value`` != prior warehouse balance + ``stock_value_difference``."""
	if not is_irr_company(company):
		return []
	currency = get_company_currency(company)
	sles = frappe.get_all(
		"Stock Ledger Entry",
		filters={
			"voucher_type": "Stock Reconciliation",
			"voucher_no": voucher_no,
			"company": company,
			"is_cancelled": 0,
		},
		fields=[
			"name",
			"item_code",
			"warehouse",
			"posting_date",
			"posting_time",
			"creation",
			"company",
			"stock_value",
			"stock_value_difference",
			"qty_after_transaction",
		],
		order_by="item_code asc, warehouse asc, posting_date asc, posting_time asc, creation asc",
	)
	issues: list[dict] = []
	for sle in sles:
		prev_qty, prev_val = _prior_warehouse_sle_before(sle)
		movement = flt(sle.stock_value_difference)
		expected = round_currency(prev_val + movement, currency)
		actual = flt(sle.stock_value)
		residual = abs(actual - expected)
		if residual > BALANCE_TOLERANCE_IRR:
			issues.append(
				{
					"sle": sle.name,
					"item_code": sle.item_code,
					"warehouse": sle.warehouse,
					"stock_value": actual,
					"expected_stock_value": expected,
					"residual": residual,
					"prev_stock_value": prev_val,
					"stock_value_difference": movement,
					"prev_qty_after": prev_qty,
					"qty_after_transaction": flt(sle.qty_after_transaction),
				}
			)
	return issues


def find_affected_stock_reconciliations(
	company: str,
	from_date: str,
	*,
	voucher_nos: list[str] | None = None,
) -> dict:
	"""Scan submitted SR vouchers and return those with warehouse balance chain breaks."""
	company = resolve_company(company)
	vouchers = _submitted_stock_reconciliations(company, from_date, voucher_nos=voucher_nos)
	affected_vouchers: list[str] = []
	items: set[str] = set()
	warehouses: set[str] = set()
	audit_rows: list[dict] = []

	for sr in vouchers:
		issues = sle_balance_issues_for_voucher(sr.name, company)
		has_issue = bool(issues)
		if has_issue:
			affected_vouchers.append(sr.name)
		for row in issues:
			items.add(row["item_code"])
			warehouses.add(row["warehouse"])
		audit_rows.append(
			{
				"voucher": sr.name,
				"item": ", ".join(sorted({i["item_code"] for i in issues})) if issues else "",
				"warehouse": ", ".join(sorted({i["warehouse"] for i in issues})) if issues else "",
				"before_balance_issue": has_issue,
				"issue_count": len(issues),
				"repost_created": False,
				"repost_name": "",
				"status": "pending",
				"sample_residual": issues[0]["residual"] if issues else 0,
			}
		)

	return {
		"company": company,
		"from_date": str(getdate(from_date)),
		"affected_vouchers": affected_vouchers,
		"affected_items": sorted(items),
		"affected_warehouses": sorted(warehouses),
		"audit": audit_rows,
		"scanned_voucher_count": len(vouchers),
	}


def _pending_repost_for_voucher(voucher_no: str) -> str | None:
	row = frappe.db.get_value(
		"Repost Item Valuation",
		{
			"voucher_type": "Stock Reconciliation",
			"voucher_no": voucher_no,
			"docstatus": 1,
			"status": ("in", ["Queued", "In Progress"]),
		},
		"name",
	)
	return row


def create_repost_item_valuation_for_sr(
	sr_name: str,
	*,
	execute_repost: bool = False,
	skip_if_pending: bool = True,
) -> dict:
	"""Create a Transaction-based Repost Item Valuation for one Stock Reconciliation."""
	if not frappe.db.exists("DocType", "Repost Item Valuation"):
		frappe.throw("Repost Item Valuation is not installed on this site")

	sr = frappe.get_doc("Stock Reconciliation", sr_name)
	if sr.docstatus != 1:
		frappe.throw(f"{sr_name} is not submitted")

	if skip_if_pending and (pending := _pending_repost_for_voucher(sr_name)):
		return {
			"voucher_no": sr_name,
			"repost_name": pending,
			"status": "skipped_existing_pending",
			"executed": False,
		}

	riv = frappe.new_doc("Repost Item Valuation")
	riv.based_on = "Transaction"
	riv.voucher_type = "Stock Reconciliation"
	riv.voucher_no = sr_name
	riv.posting_date = sr.posting_date
	riv.posting_time = sr.posting_time
	riv.company = sr.company
	riv.allow_negative_stock = 1
	riv.repost_only_accounting_ledgers = 0
	riv.flags.ignore_permissions = True
	if not execute_repost:
		riv.flags.dont_run_in_test = True
	riv.insert(ignore_permissions=True)
	riv.submit()

	out = {
		"voucher_no": sr_name,
		"repost_name": riv.name,
		"status": riv.status,
		"executed": False,
	}

	if execute_repost:
		from erpnext.stock.doctype.repost_item_valuation.repost_item_valuation import repost

		repost(riv)
		riv.reload()
		out["status"] = riv.status
		out["executed"] = True

	return out


def bulk_repost_stock_reconciliation_valuation(
	*,
	from_date: str,
	company: str,
	dry_run: bool = True,
	voucher_nos: list[str] | None = None,
	execute_repost: bool = False,
	skip_if_pending: bool = True,
) -> dict:
	"""Detect affected SR vouchers and optionally queue standard Repost Item Valuation jobs."""
	scan = find_affected_stock_reconciliations(company, from_date, voucher_nos=voucher_nos)
	result = {
		"dry_run": dry_run,
		"execute_repost": execute_repost,
		**{k: scan[k] for k in ("company", "from_date", "affected_vouchers", "affected_items", "affected_warehouses", "scanned_voucher_count")},
		"audit": scan["audit"],
		"created_repost_jobs": [],
	}

	if dry_run:
		return result

	if not scan["affected_vouchers"]:
		return result

	audit_by_voucher = {row["voucher"]: row for row in result["audit"]}
	created: list[dict] = []

	for voucher_no in scan["affected_vouchers"]:
		try:
			job = create_repost_item_valuation_for_sr(
				voucher_no,
				execute_repost=execute_repost,
				skip_if_pending=skip_if_pending,
			)
			created.append(job)
			row = audit_by_voucher.get(voucher_no)
			if row:
				row["repost_created"] = job.get("repost_name") and job.get("status") != "skipped_existing_pending"
				row["repost_name"] = job.get("repost_name") or ""
				row["status"] = job.get("status") or ""
		except Exception as exc:
			created.append({"voucher_no": voucher_no, "status": "failed", "error": str(exc)})
			row = audit_by_voucher.get(voucher_no)
			if row:
				row["status"] = f"failed: {exc!s}"

	result["created_repost_jobs"] = created
	if not dry_run:
		frappe.db.commit()
	return result


@frappe.whitelist()
def repost_stock_reconciliation_valuation(
	from_date: str,
	company: str,
	dry_run: int | str = 1,
	voucher_nos: str | list | None = None,
	execute_repost: int | str = 0,
) -> dict:
	"""Whitelisted entry (Administrator / Stock Manager). ``dry_run=1`` reports only."""
	frappe.only_for(("System Manager", "Stock Manager"))

	parsed_vouchers: list[str] | None = None
	if voucher_nos:
		if isinstance(voucher_nos, str):
			voucher_nos = json.loads(voucher_nos) if voucher_nos.strip().startswith("[") else [voucher_nos]
		parsed_vouchers = list(voucher_nos)

	return bulk_repost_stock_reconciliation_valuation(
		from_date=from_date,
		company=company,
		dry_run=cint(dry_run),
		voucher_nos=parsed_vouchers,
		execute_repost=cint(execute_repost),
	)


def run(
	from_date: str = "2026-03-21",
	company: str = "",
	dry_run: bool = True,
	voucher_nos: list[str] | None = None,
	execute_repost: bool = False,
) -> dict:
	"""``bench execute …repost_stock_reconciliation_valuation.run`` entry point."""
	if not company:
		company = frappe.db.get_value("Company", {"default_currency": "IRR"}, "name") or ""
	return bulk_repost_stock_reconciliation_valuation(
		from_date=from_date,
		company=company,
		dry_run=dry_run,
		voucher_nos=voucher_nos,
		execute_repost=execute_repost,
	)


def validate_item_warehouse_balance_sample(
	item_code: str,
	warehouse: str,
	voucher_no: str,
	*,
	sle_index: int = 1,
) -> dict:
	"""Read-only check: compare SLE row balance to expected cumulative (0-based ``sle_index``)."""
	sles = frappe.get_all(
		"Stock Ledger Entry",
		filters={
			"voucher_type": "Stock Reconciliation",
			"voucher_no": voucher_no,
			"item_code": item_code,
			"warehouse": warehouse,
			"is_cancelled": 0,
		},
		fields=["name", "stock_value", "stock_value_difference", "qty_after_transaction"],
		order_by="creation asc",
	)
	if sle_index >= len(sles):
		frappe.throw(f"SLE index {sle_index} out of range (count={len(sles)})")
	sle = sles[sle_index]
	company = frappe.db.get_value("Stock Reconciliation", voucher_no, "company")
	currency = get_company_currency(company)
	full = frappe.get_doc("Stock Ledger Entry", sle.name)
	prev_qty, prev_val = _prior_warehouse_sle_before(full)
	expected = round_currency(prev_val + flt(sle.stock_value_difference), currency)
	return {
		"voucher_no": voucher_no,
		"item_code": item_code,
		"warehouse": warehouse,
		"sle_index": sle_index,
		"sle_name": sle.name,
		"stock_value": flt(sle.stock_value),
		"expected_stock_value": expected,
		"qty_after_transaction": flt(sle.qty_after_transaction),
		"residual": abs(flt(sle.stock_value) - expected),
	}
