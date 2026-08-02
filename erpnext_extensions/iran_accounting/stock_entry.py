# Copyright (c) 2026, ERPNext Extensions contributors

from __future__ import annotations

import frappe
from frappe.utils import flt

from erpnext_extensions.iran_accounting.manufacture_rounding import (
	align_manufacture_finished_good_residual,
	align_manufacture_finished_good_to_outgoing,
)
from erpnext_extensions.iran_accounting.qty_rate_amount import align_stock_entry_item_amounts
from erpnext_extensions.iran_accounting.rounding import (
	get_company_currency,
	get_currency_precision,
	is_irr_company,
	round_currency,
	round_stock_entry_totals,
)
from erpnext_extensions.iran_accounting.zero_value_transfer import ZERO_VALUE_TRANSFER_STOCK_ENTRY_PURPOSES


def align_zero_value_transfer_totals(doc) -> None:
	"""For IRR internal transfers, collapse rounding-only incoming/outgoing mismatch."""
	if doc.doctype != "Stock Entry" or not is_irr_company(doc.company):
		return
	if doc.purpose not in ZERO_VALUE_TRANSFER_STOCK_ENTRY_PURPOSES:
		return
	company_currency = get_company_currency(doc.company)
	precision = get_currency_precision(company_currency)
	inc = round_currency(doc.total_incoming_value, company_currency)
	out = round_currency(doc.total_outgoing_value, company_currency)
	if inc == out:
		doc.total_incoming_value = inc
		doc.total_outgoing_value = out
		doc.value_difference = 0
		return
	diff = abs(flt(inc) - flt(out))
	max_tol = 1 if precision == 0 else (1.0 / (10**precision))
	if diff <= max_tol:
		aligned = max(inc, out) if precision == 0 else max(inc, out)
		doc.total_incoming_value = aligned
		doc.total_outgoing_value = aligned
		doc.value_difference = 0


def validate_stock_entry(doc, method=None):
	if not is_irr_company(doc.company):
		return
	align_stock_entry_item_amounts(doc)
	round_stock_entry_totals(doc)
	align_manufacture_finished_good_residual(doc)
	from erpnext_extensions.iran_accounting.domain.irr_rounding_residual import (
		assert_round_off_ready_if_needed,
	)

	assert_round_off_ready_if_needed(doc)


def before_submit_stock_entry(doc, method=None):
	validate_stock_entry(doc, method)
	if not is_irr_company(doc.company):
		return
	if hasattr(doc, "set_total_incoming_outgoing_value"):
		doc.set_total_incoming_outgoing_value()
	align_manufacture_finished_good_residual(doc)
	align_zero_value_transfer_totals(doc)
	from erpnext_extensions.iran_accounting.domain.irr_rounding_residual import (
		assert_round_off_ready_if_needed,
	)

	assert_round_off_ready_if_needed(doc)


def on_submit_stock_entry(doc, method=None):
	if not is_irr_company(doc.company):
		return
	# ERPNext may rewrite row rates from moving-average floats after before_submit.
	# Re-apply rate-first integers and persist so Desk / contract see the contract rates.
	align_stock_entry_item_amounts(doc)
	for row in doc.get("items") or []:
		row.db_update()
	from erpnext_extensions.iran_accounting.domain.stock_entry_ledger_contract import (
		enforce_stock_entry_ledger_contract,
	)

	enforce_stock_entry_ledger_contract(doc.name, doc.company, raise_on_fail=True)


def before_gl_preview_stock_entry(doc, method=None):
	if doc.doctype != "Stock Entry":
		return
	if hasattr(doc, "calculate_rate_and_amount"):
		doc.calculate_rate_and_amount(reset_outgoing_rate=False, raise_error_if_no_rate=False)
	if is_irr_company(doc.company) and hasattr(doc, "set_total_incoming_outgoing_value"):
		doc.set_total_incoming_outgoing_value()
	round_stock_entry_totals(doc)
	align_manufacture_finished_good_residual(doc)
	align_zero_value_transfer_totals(doc)


def patched_set_total_incoming_outgoing_value(self):
	"""IRR-aware totals; bound to Stock Entry when monkey patches apply."""
	if not is_irr_company(self.company):
		if _original_set_total_incoming_outgoing_value:
			return _original_set_total_incoming_outgoing_value(self)
		return

	company_currency = get_company_currency(self.company)
	self.total_incoming_value = self.total_outgoing_value = 0.0
	for d in self.get("items"):
		if d.t_warehouse:
			self.total_incoming_value += flt(d.amount)
		if d.s_warehouse:
			self.total_outgoing_value += flt(d.amount)

	# Do not round summed totals — rows are already IRR integers.
	self.value_difference = flt(self.total_incoming_value) - flt(self.total_outgoing_value)
	align_manufacture_finished_good_residual(self)
	align_zero_value_transfer_totals(self)


_original_set_total_incoming_outgoing_value = None
