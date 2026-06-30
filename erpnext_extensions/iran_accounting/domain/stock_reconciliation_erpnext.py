# Copyright (c) 2026, ERPNext Extensions contributors
"""ERPNext Stock Reconciliation class overrides (header / row totals)."""

from __future__ import annotations

from erpnext_extensions.iran_accounting.domain.qty_rate_amount import override_difference_amount


def patched_set_total_qty_and_amount(self) -> None:
	"""Replace ERPNext row totals + header; single source: iran_accounting financial rounding."""
	override_difference_amount(self)


def patched_calculate_difference_amount(self, item, item_dict) -> None:
	"""ERPNext accumulates header here during remove_items_with_no_change — disabled."""
	return


def patched_remove_items_with_no_change(self) -> None:
	"""Run ERPNext row filter; never leave header on ERPNext difference_amount accumulation."""
	StockReconciliation = self.__class__
	StockReconciliation._iran_original_remove_items_with_no_change(self)
	override_difference_amount(self)
