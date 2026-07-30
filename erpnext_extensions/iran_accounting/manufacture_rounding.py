# Copyright (c) 2026, ERPNext Extensions contributors
"""Manufacture residual alignment — never wipe legitimate capitalization."""

from __future__ import annotations

from frappe.utils import flt

from erpnext_extensions.iran_accounting.rounding import (
	get_company_currency,
	get_currency_precision,
	is_irr_company,
	round_currency,
)


def _residual_tolerance(currency: str) -> float:
	precision = get_currency_precision(currency)
	return 1.0 if precision == 0 else (1.0 / (10**precision))


def _row_capitalized_cost(row) -> float:
	return flt(row.get("additional_cost")) + flt(row.get("landed_cost_voucher_amount"))


def align_manufacture_finished_good_residual(doc) -> None:
	"""Single-FG Manufacture: absorb only true IRR rounding residuals.

	Expected economic identity (simple single FG):
	  incoming ≈ outgoing + FG capitalized costs (additional_cost + LCV)

	Never force Incoming = Outgoing or value_difference = 0 when capitalized
	cost exceeds residual tolerance. Multi-FG is skipped. Repack is skipped
	(purpose must be Manufacture).
	"""
	if doc.doctype != "Stock Entry" or doc.purpose != "Manufacture":
		return
	if not is_irr_company(doc.company):
		return

	fg_rows = [
		row
		for row in doc.get("items") or []
		if row.get("is_finished_item") and row.get("t_warehouse")
	]
	if len(fg_rows) != 1:
		return

	currency = get_company_currency(doc.company)
	tol = _residual_tolerance(currency)

	outgoing_total = sum(flt(row.amount) for row in doc.get("items") or [] if row.get("s_warehouse"))
	incoming_total = sum(flt(row.amount) for row in doc.get("items") or [] if row.get("t_warehouse"))

	fg = fg_rows[0]
	qty = flt(fg.transfer_qty if fg.get("transfer_qty") not in (None, "") else fg.get("qty"))
	if not qty:
		return

	capitalized = _row_capitalized_cost(fg)
	# Other incoming rows (scrap/secondary) keep their amounts.
	other_incoming = incoming_total - flt(fg.amount)
	composed_fg = round_currency(
		flt(fg.basic_amount) + capitalized,
		currency,
	)
	if capitalized > tol:
		# Legitimate capitalization: only nudge FG amount within residual of composed truth.
		target = composed_fg
		if abs(flt(fg.amount) - target) > tol:
			return
		if abs(flt(fg.amount) - target) == 0:
			_refresh_header_totals(doc)
			return
		_apply_fg_amount(fg, target, qty, currency)
		_refresh_header_totals(doc)
		return

	# No material capitalization on FG: absorb Incoming vs Outgoing only within residual tol.
	expected_incoming = round_currency(outgoing_total + other_incoming, currency)
	# With single FG and no other incoming, expected_incoming == outgoing.
	delta = abs(incoming_total - outgoing_total)
	if delta > tol:
		return
	if delta == 0:
		_refresh_header_totals(doc)
		return

	# Align FG so incoming equals outgoing (true ±1 IRR case).
	target_fg = round_currency(outgoing_total - other_incoming, currency)
	_apply_fg_amount(fg, target_fg, qty, currency)
	# Keep basic_* consistent with material-only target when no capitalized cost.
	fg.basic_amount = target_fg
	fg.basic_rate = flt(target_fg / qty) if qty else fg.basic_rate
	_refresh_header_totals(doc)


def _apply_fg_amount(fg, amount: float, qty: float, currency: str) -> None:
	fg.amount = round_currency(amount, currency)
	capitalized = _row_capitalized_cost(fg)
	if capitalized > _residual_tolerance(currency):
		# Preserve ERPNext basic_* ownership; only amount/valuation absorb residual.
		fg.valuation_rate = flt(fg.amount) / qty if qty else fg.valuation_rate
		return
	fg.basic_amount = fg.amount
	fg.basic_rate = flt(fg.amount / qty) if qty else fg.basic_rate
	fg.valuation_rate = fg.basic_rate


def _refresh_header_totals(doc) -> None:
	inc = sum(flt(d.amount) for d in doc.get("items") or [] if d.get("t_warehouse"))
	out = sum(flt(d.amount) for d in doc.get("items") or [] if d.get("s_warehouse"))
	doc.total_incoming_value = inc
	doc.total_outgoing_value = out
	doc.value_difference = flt(inc) - flt(out)


# Backward-compatible name used by hooks / repost.
def align_manufacture_finished_good_to_outgoing(doc) -> None:
	align_manufacture_finished_good_residual(doc)
