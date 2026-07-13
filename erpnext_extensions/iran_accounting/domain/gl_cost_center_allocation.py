# Copyright (c) 2026, ERPNext Extensions contributors
"""IRR-safe cost center allocation: split legs must sum to the pre-split amount."""

from __future__ import annotations

import copy

import frappe
from frappe.utils import flt

from erpnext_extensions.iran_accounting.domain.currency import get_currency_precision, is_irr_company

_SPLIT_FIELDS = (
	"debit",
	"credit",
	"debit_in_account_currency",
	"credit_in_account_currency",
)


def absorb_irr_cost_center_split_residual(gle_list: list, template: dict, precision: int) -> None:
	"""After percentage splits, restore exact totals per monetary field (IRR integer)."""
	if not gle_list:
		return
	target = gle_list[-1]
	for field in _SPLIT_FIELDS:
		original = flt(template.get(field), precision)
		if not original:
			continue
		split_sum = sum(flt(g.get(field), precision) for g in gle_list)
		residual = flt(original - split_sum, precision)
		if residual:
			target[field] = flt(flt(target.get(field)) + residual, precision)


def distribute_gl_based_on_cost_center_allocation_irr(gl_map, precision=None, from_repost=False):
	"""Drop-in replacement for ERPNext distribute_gl with exact IRR splits."""
	from erpnext.accounts.general_ledger import (
		distribute_gl_based_on_cost_center_allocation as _orig,
	)
	from erpnext.accounts.general_ledger import (
		get_cost_center_allocation_data,
		validate_expense_against_budget,
	)

	if not gl_map:
		return []

	company = gl_map[0].company
	company_currency = frappe.get_cached_value("Company", company, "default_currency")
	if not is_irr_company(company):
		return _orig(gl_map, precision=precision, from_repost=from_repost)

	if not precision:
		precision = get_currency_precision(company_currency)

	round_off_account = frappe.get_cached_value("Company", company, "round_off_account")

	new_gl_map = []
	for d in gl_map:
		cost_center = d.get("cost_center")
		cost_center_allocation = get_cost_center_allocation_data(
			company, gl_map[0]["posting_date"], cost_center
		)
		if not cost_center_allocation:
			new_gl_map.append(d)
			continue

		if not from_repost:
			validate_expense_against_budget(
				d, expense_amount=flt(d.debit, precision) - flt(d.credit, precision)
			)

		if d.account == round_off_account:
			d.cost_center = cost_center_allocation[0][0]
			new_gl_map.append(d)
			continue

		gle_list = []
		for sub_cost_center, percentage in cost_center_allocation:
			gle = copy.deepcopy(d)
			gle.cost_center = sub_cost_center
			for field in _SPLIT_FIELDS:
				gle[field] = flt(flt(d.get(field)) * percentage / 100, precision)
			gle_list.append(gle)

		absorb_irr_cost_center_split_residual(gle_list, d, precision)
		new_gl_map.extend(gle_list)

	return new_gl_map
