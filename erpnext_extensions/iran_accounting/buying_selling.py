# Copyright (c) 2026, ERPNext Extensions contributors

from __future__ import annotations

from erpnext_extensions.iran_accounting.qty_rate_amount import (
	align_delivery_note_item_amounts,
	align_purchase_order_item_amounts,
	align_purchase_receipt_item_amounts,
)


def validate_purchase_order(doc, method=None) -> None:
	align_purchase_order_item_amounts(doc)


def validate_purchase_receipt(doc, method=None) -> None:
	align_purchase_receipt_item_amounts(doc)
	from erpnext_extensions.iran_accounting.domain.currency import is_irr_company
	from erpnext_extensions.iran_accounting.domain.irr_rounding_residual import (
		assert_round_off_ready_if_needed,
	)

	if is_irr_company(doc.company):
		assert_round_off_ready_if_needed(doc)


def validate_delivery_note(doc, method=None) -> None:
	align_delivery_note_item_amounts(doc)
