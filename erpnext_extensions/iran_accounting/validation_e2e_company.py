# Copyright (c) 2026, ERPNext Extensions contributors
"""Company-wide qty×rate / difference_amount / GL-SLE consistency scan."""

from __future__ import annotations

from typing import Any

import frappe
from frappe.utils import flt

from erpnext_extensions.iran_accounting.qty_rate_consistency import check_qty_rate_amount_consistency
from erpnext_extensions.iran_accounting.rounding import amount_is_fractional, get_company_currency, is_irr_company


VOUCHER_TYPES = (
	"Stock Reconciliation",
	"Stock Entry",
	"Purchase Receipt",
	"Purchase Invoice",
	"Sales Invoice",
	"Delivery Note",
)


@frappe.whitelist()
def check_qty_rate_amount_consistency_for_company(
	company: str = "ESPAD",
	limit_per_doctype: int = 25,
) -> dict[str, Any]:
	"""Run row/document/ledger checks on recent submitted vouchers."""
	frappe.set_user("Administrator")
	from erpnext_extensions.iran_accounting.integration.bootstrap import apply

	apply()
	ccy = get_company_currency(company)
	irr = is_irr_company(company)
	failures: list[dict] = []
	checked = 0
	passed = 0
	for doctype in VOUCHER_TYPES:
		names = frappe.get_all(
			doctype,
			filters={"company": company, "docstatus": 1},
			pluck="name",
			order_by="modified desc",
			limit=limit_per_doctype,
		)
		for name in names:
			checked += 1
			try:
				out = check_qty_rate_amount_consistency(doctype, name, company)
			except Exception as exc:
				failures.append({"doctype": doctype, "voucher_no": name, "error": str(exc)})
				continue
			if out.get("status") == "PASS":
				passed += 1
			else:
				failures.append(
					{
						"doctype": doctype,
						"voucher_no": name,
						"status": out.get("status"),
						"consistency_failures": out.get("consistency_failures"),
						"row_fail_count": out.get("row_fail_count"),
					}
				)
			if doctype == "Stock Reconciliation":
				_check_sr_row_nulls(name, failures)
				if irr:
					_check_sr_irr_fractional(name, failures)

	status = "PASS" if not failures else "FAIL"
	return {
		"company": company,
		"currency": ccy,
		"checked": checked,
		"passed": passed,
		"status": status,
		"failures": failures[:50],
		"failure_count": len(failures),
	}


def _check_sr_row_nulls(voucher_no: str, failures: list) -> None:
	rows = frappe.get_all(
		"Stock Reconciliation Item",
		filters={"parent": voucher_no},
		fields=["name", "qty", "valuation_rate", "amount", "amount_difference"],
	)
	for r in rows:
		if flt(r.qty) and r.valuation_rate not in (None, "") and r.amount in (None, ""):
			failures.append(
				{"voucher_no": voucher_no, "issue": "NULL row amount with qty+rate", "row": r.name}
			)


def _check_sr_irr_fractional(voucher_no: str, failures: list) -> None:
	for field in ("amount", "current_amount", "amount_difference"):
		rows = frappe.db.sql(
			f"""
			select name, `{field}` as val from `tabStock Reconciliation Item`
			where parent=%s and `{field}` is not null
			""",
			voucher_no,
			as_dict=True,
		)
		for r in rows:
			if amount_is_fractional(r.val, "IRR"):
				failures.append(
					{
						"voucher_no": voucher_no,
						"issue": f"IRR fractional {field}",
						"row": r.name,
						"value": r.val,
					}
				)
