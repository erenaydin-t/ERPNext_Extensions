# Copyright (c) 2026, ERPNext Extensions contributors
"""Read-only detector: fractional IRR rates vs rate-first contract amounts.

Never writes. Never repairs. Suitable for production scan reports.
"""

from __future__ import annotations

from typing import Any

import frappe
from frappe.utils import flt

from erpnext_extensions.iran_accounting.domain.currency import (
	amount_rate_qty_residual,
	get_company_currency,
	integer_valuation_rate_from_amount,
	is_irr_company,
	rate_is_fractional,
	round_monetary_rate,
	round_row_amount,
)
from erpnext_extensions.iran_accounting.domain.qty_rate_amount import compose_stock_entry_row_amount


def _downstream_dependency_count(voucher_no: str) -> int:
	"""Count submitted dependents that may be affected by a rate repair (read-only)."""
	count = 0
	count += frappe.db.count(
		"Repost Item Valuation",
		{"voucher_no": voucher_no, "docstatus": ["<", 2]},
	)
	try:
		count += int(
			frappe.db.sql(
				"""
				select count(distinct parent)
				from `tabLanded Cost Purchase Receipt`
				where receipt_document=%s
				""",
				voucher_no,
			)[0][0]
			or 0
		)
	except Exception:
		pass
	return int(count)


def detect_fractional_irr_stock_entry_rates(
	company: str | None = None,
	*,
	limit: int = 500,
	purposes: tuple[str, ...] | None = None,
) -> dict[str, Any]:
	"""Scan submitted Stock Entries for fractional IRR rates / product-first amounts.

	Returns a report dict. No writes.
	"""
	if company and not is_irr_company(company):
		return {"status": "SKIP", "reason": "not_irr", "rows": []}

	filters: dict[str, Any] = {"docstatus": 1}
	if company:
		filters["company"] = company
	if purposes:
		filters["purpose"] = ["in", list(purposes)]

	entries = frappe.get_all(
		"Stock Entry",
		filters=filters,
		fields=["name", "purpose", "company"],
		order_by="modified desc",
		limit_page_length=limit,
	)

	rows_out: list[dict] = []
	for ste in entries:
		ccy = get_company_currency(ste.company)
		if not is_irr_company(ste.company):
			continue
		details = frappe.get_all(
			"Stock Entry Detail",
			filters={"parent": ste.name},
			fields=[
				"name",
				"idx",
				"item_code",
				"qty",
				"transfer_qty",
				"basic_rate",
				"basic_amount",
				"additional_cost",
				"landed_cost_voucher_amount",
				"amount",
				"valuation_rate",
			],
			order_by="idx asc",
		)
		for detail in details:
			transfer_qty = flt(
				detail.transfer_qty if detail.transfer_qty not in (None, "") else detail.qty
			)
			stored_rate = detail.basic_rate
			if stored_rate in (None, ""):
				continue
			int_rate = round_monetary_rate(stored_rate, ccy)
			contract_basic = round_row_amount(transfer_qty, int_rate, ccy) if transfer_qty else 0
			# Compose contract amount with stored (rounded) capitalized costs
			probe = frappe._dict(
				{
					"basic_amount": contract_basic,
					"additional_cost": round_monetary_rate(detail.additional_cost or 0, ccy)
					if detail.additional_cost not in (None, "")
					else 0,
					"landed_cost_voucher_amount": round_monetary_rate(
						detail.landed_cost_voucher_amount or 0, ccy
					)
					if detail.landed_cost_voucher_amount not in (None, "")
					else 0,
				}
			)
			# additional_cost is amount not rate — use round_currency via compose
			from erpnext_extensions.iran_accounting.domain.currency import round_currency

			probe.additional_cost = round_currency(detail.additional_cost or 0, ccy)
			probe.landed_cost_voucher_amount = round_currency(
				detail.landed_cost_voucher_amount or 0, ccy
			)
			contract_amount = compose_stock_entry_row_amount(probe, ccy)
			contract_val_rate = (
				integer_valuation_rate_from_amount(contract_amount, transfer_qty, ccy)
				if transfer_qty and contract_amount
				else int_rate
			)

			rate_frac = rate_is_fractional(stored_rate, ccy)
			val_frac = rate_is_fractional(detail.valuation_rate, ccy) if detail.valuation_rate not in (None, "") else False
			amount_delta = flt(detail.amount) - flt(contract_amount)
			if not rate_frac and not val_frac and abs(amount_delta) < 0.5:
				continue

			sle_delta = None
			gl_delta = None
			sle_row = frappe.db.get_value(
				"Stock Ledger Entry",
				{
					"voucher_type": "Stock Entry",
					"voucher_no": ste.name,
					"voucher_detail_no": detail.name,
					"is_cancelled": 0,
				},
				["stock_value_difference", "incoming_rate", "outgoing_rate", "valuation_rate"],
				as_dict=True,
			)
			if sle_row:
				sle_delta = abs(flt(sle_row.stock_value_difference)) - abs(flt(contract_amount))

			gl_rows = frappe.get_all(
				"GL Entry",
				filters={"voucher_type": "Stock Entry", "voucher_no": ste.name, "is_cancelled": 0},
				fields=["debit", "credit"],
			)
			if gl_rows:
				gl_mag = max(sum(flt(r.debit) for r in gl_rows), sum(flt(r.credit) for r in gl_rows))
				# Voucher-level signal only
				gl_delta = gl_mag  # reported as magnitude; caller compares to Σ contract

			rows_out.append(
				{
					"voucher": ste.name,
					"purpose": ste.purpose,
					"company": ste.company,
					"row": detail.idx,
					"row_name": detail.name,
					"item_code": detail.item_code,
					"qty": transfer_qty,
					"stored_fractional_rate": stored_rate,
					"required_integer_rate": int_rate,
					"stored_amount": detail.amount,
					"contract_amount": contract_amount,
					"delta": amount_delta,
					"stored_valuation_rate": detail.valuation_rate,
					"contract_valuation_rate": contract_val_rate,
					"valuation_residual": amount_rate_qty_residual(
						contract_amount, transfer_qty, contract_val_rate, ccy
					)
					if transfer_qty
					else 0,
					"sle_delta": sle_delta,
					"gl_delta": gl_delta,
					"downstream_dependency_count": _downstream_dependency_count(ste.name),
					"rate_is_fractional": rate_frac,
					"valuation_rate_is_fractional": val_frac,
				}
			)

	abs_delta = sum(abs(flt(r["delta"])) for r in rows_out)
	return {
		"status": "OK",
		"company": company,
		"scanned_vouchers": len(entries),
		"affected_rows": len(rows_out),
		"abs_delta_total": abs_delta,
		"rows": rows_out,
	}


def detect_mat_ste_03516_pattern(company: str | None = None, *, limit: int = 200) -> dict[str, Any]:
	"""Convenience scan focused on Material Transfer for Manufacture rate-first gaps."""
	return detect_fractional_irr_stock_entry_rates(
		company,
		limit=limit,
		purposes=("Material Transfer for Manufacture",),
	)
