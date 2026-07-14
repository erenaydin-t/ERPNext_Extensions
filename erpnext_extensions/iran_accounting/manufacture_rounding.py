# Copyright (c) 2026, ERPNext Extensions contributors

from __future__ import annotations

from frappe.utils import flt

from erpnext_extensions.iran_accounting.rounding import (
	get_company_currency,
	is_irr_company,
	round_currency,
)


def align_manufacture_finished_good_to_outgoing(doc) -> None:
	"""
	Single-FG Manufacture: incoming integer total must equal sum of outgoing line amounts.
	Prevents 1-Rial rounding discrepancy in IRR currency.
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
	outgoing_total = sum(
		flt(row.amount) for row in doc.get("items") or [] if row.get("s_warehouse")
	)

	fg = fg_rows[0]
	qty = flt(fg.transfer_qty or fg.qty)
	if not qty:
		return

	fg_amount = round_currency(outgoing_total, currency)
	fg.basic_amount = fg_amount
	fg.amount = fg_amount
	fg.basic_rate = flt(outgoing_total / qty)
	fg.valuation_rate = fg.basic_rate

	doc.total_outgoing_value = outgoing_total
	doc.total_incoming_value = fg_amount
	doc.value_difference = 0
