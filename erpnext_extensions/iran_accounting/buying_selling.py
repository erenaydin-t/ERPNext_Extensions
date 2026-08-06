# Copyright (c) 2026, ERPNext Extensions contributors

from __future__ import annotations

from erpnext_extensions.iran_accounting.qty_rate_amount import (
	align_delivery_note_item_amounts,
	align_purchase_order_item_amounts,
	align_purchase_receipt_item_amounts,
)


def update_regional_item_valuation_rate(doc) -> None:
	"""ERPNext regional hook at the end of BuyingController.update_valuation_rate.

	Single IRR integer-rate pipeline for every UVR caller (Purchase Receipt,
	Purchase Return, Landed Cost Voucher, RIV recalculation, Purchase Invoice
	with update stock). Reuses align_purchase_receipt_item_amounts — does not
	recompute valuation_rate.
	"""
	align_purchase_receipt_item_amounts(doc)


def validate_purchase_order(doc, method=None) -> None:
	align_purchase_order_item_amounts(doc)


def validate_purchase_receipt(doc, method=None) -> None:
	# Align remains here for idempotent safety if UVR was not run on this path;
	# primary IRR VR integerization is update_regional_item_valuation_rate (UVR).
	align_purchase_receipt_item_amounts(doc)
	from erpnext_extensions.iran_accounting.domain.currency import is_irr_company
	from erpnext_extensions.iran_accounting.domain.irr_rounding_residual import (
		assert_round_off_ready_if_needed,
	)

	if is_irr_company(doc.company):
		assert_round_off_ready_if_needed(doc)


def validate_delivery_note(doc, method=None) -> None:
	align_delivery_note_item_amounts(doc)
