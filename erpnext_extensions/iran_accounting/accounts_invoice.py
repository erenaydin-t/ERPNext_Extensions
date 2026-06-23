# Copyright (c) 2026, ERPNext Extensions contributors

from __future__ import annotations

from erpnext_extensions.iran_accounting.rounding import (
	get_company_currency,
	is_irr_company,
	round_currency,
)

IRR_INVOICE_BASE_FIELDS = (
	"base_net_total",
	"base_total",
	"base_grand_total",
	"base_total_taxes_and_charges",
	"base_discount_amount",
	"base_rounded_total",
)

IRR_INVOICE_ITEM_BASE_FIELDS = (
	"base_rate",
	"base_amount",
	"base_net_rate",
	"base_net_amount",
)

IRR_TAX_BASE_FIELDS = ("base_tax_amount",)


def round_irr_invoice_totals(doc, method=None) -> None:
	"""IRR companies: company-currency totals on buying/selling invoices must be whole rials."""
	if doc.doctype not in ("Purchase Invoice", "Sales Invoice"):
		return
	if not is_irr_company(doc.company):
		return
	currency = get_company_currency(doc.company)
	for field in IRR_INVOICE_BASE_FIELDS:
		if doc.meta.has_field(field) and doc.get(field) is not None:
			doc.set(field, round_currency(doc.get(field), currency))
	for row in doc.get("items") or []:
		for field in IRR_INVOICE_ITEM_BASE_FIELDS:
			if row.get(field) is not None:
				row.set(field, round_currency(row.get(field), currency))
	for row in doc.get("taxes") or []:
		for field in IRR_TAX_BASE_FIELDS:
			if row.get(field) is not None:
				row.set(field, round_currency(row.get(field), currency))
