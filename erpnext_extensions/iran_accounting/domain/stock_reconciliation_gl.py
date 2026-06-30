# Copyright (c) 2026, ERPNext Extensions contributors
"""Stock Reconciliation GL from row-level amounts only (never SLE engine)."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt

from erpnext.accounts.general_ledger import process_gl_map

from erpnext_extensions.iran_accounting.domain.currency import get_company_currency, round_currency
from erpnext_extensions.iran_accounting.domain.qty_rate_amount import (
	override_difference_amount,
	sum_stock_reconciliation_row_amounts,
)


def stock_reconciliation_row_gl_movement(sle, company: str) -> float:
	"""Signed GL leg = row amount_difference (from round(qty×rate) − current_amount)."""
	if not sle.voucher_detail_no:
		return 0.0
	ccy = get_company_currency(company)
	row = frappe.db.get_value(
		"Stock Reconciliation Item",
		sle.voucher_detail_no,
		["amount_difference", "amount", "current_amount"],
		as_dict=True,
	)
	if not row:
		return 0.0
	if row.amount_difference not in (None, ""):
		return flt(round_currency(row.amount_difference, ccy))
	if row.amount not in (None, "") and row.current_amount not in (None, ""):
		return flt(round_currency(flt(row.amount) - flt(row.current_amount), ccy))
	return 0.0


def get_stock_reconciliation_gl_entries(
	self,
	inventory_account_map=None,
	default_expense_account=None,
	default_cost_center=None,
):
	"""Mirror ERPNext GL layout; amounts from Stock Reconciliation Item rows only."""
	if not inventory_account_map:
		inventory_account_map = self.get_inventory_account_map()

	override_difference_amount(self)

	sle_map = self.get_stock_ledger_details()
	voucher_details = self.get_voucher_details(default_expense_account, default_cost_center, sle_map)

	gl_list = []
	warehouse_with_no_account = []
	precision = self.get_debit_field_precision()

	for item_row in voucher_details:
		sle_list = sle_map.get(item_row.name) or []
		for sle in sle_list:
			_inv_dict = self.get_inventory_account_dict(sle, inventory_account_map)
			if not _inv_dict.get("account"):
				if sle.warehouse not in warehouse_with_no_account:
					warehouse_with_no_account.append(sle.warehouse)
				continue

			mov = stock_reconciliation_row_gl_movement(sle, self.company)
			self.check_expense_account(item_row)
			expense_account = item_row.expense_account

			gl_list.append(
				self.get_gl_dict(
					{
						"account": _inv_dict["account"],
						"against": expense_account,
						"cost_center": item_row.cost_center,
						"project": sle.get("project") or item_row.project or self.get("project"),
						"remarks": self.get("remarks") or _("Accounting Entry for Stock"),
						"debit": mov,
						"is_opening": item_row.get("is_opening") or self.get("is_opening") or "No",
					},
					_inv_dict["account_currency"],
					item=item_row,
				)
			)

			gl_list.append(
				self.get_gl_dict(
					{
						"account": expense_account,
						"against": _inv_dict["account"],
						"cost_center": item_row.cost_center,
						"remarks": self.get("remarks") or _("Accounting Entry for Stock"),
						"debit": -1 * mov,
						"project": sle.get("project") or item_row.get("project") or self.get("project"),
						"is_opening": item_row.get("is_opening") or self.get("is_opening") or "No",
					},
					item=item_row,
				)
			)

	if warehouse_with_no_account:
		for wh in warehouse_with_no_account:
			if frappe.get_cached_value("Warehouse", wh, "company"):
				frappe.throw(
					_(
						"Warehouse {0} is not linked to any account, please mention the account in the warehouse record or set default inventory account in company {1}."
					).format(wh, self.company)
				)

	gl_map = process_gl_map(
		gl_list, precision=precision, from_repost=frappe.flags.through_repost_item_valuation
	)
	return gl_map


def log_gl_generation_triggered(doc) -> None:
	import logging

	logger = logging.getLogger(__name__)
	override_difference_amount(doc)
	sum_row = sum_stock_reconciliation_row_amounts(doc)
	logger.info(
		"GL_GENERATION_TRIGGERED voucher_no=%s sum_row_amount=%s difference_amount=%s purpose=%s",
		doc.name,
		sum_row,
		flt(doc.difference_amount),
		doc.purpose,
	)
