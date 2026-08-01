# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt, nowdate

from erpnext_extensions.consignment_stock.accounting import (
	get_temporary_clearing_account,
	get_valuation_difference_account,
	resolve_cost_center_from_stock_entry,
	resolve_finance_book_from_stock_entry,
)
from erpnext_extensions.consignment_stock.constants import (
	F_IS_RETURN,
	F_JE_ROLE,
	F_ORIGINAL_RATE,
	F_PARTY,
	F_PARTY_TYPE,
	F_RECEIPT_SE,
	F_SETTLEMENT_AMOUNT,
	F_SETTLEMENT_JE,
	JE_ROLE_SETTLEMENT,
)
from erpnext_extensions.consignment_stock.party import resolve_party_account


def compute_settlement_amounts(stock_entry) -> dict:
	"""R = sum settlement amounts (qty × original receipt rate); A = actual outgoing value; D = A - R."""
	precision = stock_entry.precision("total_outgoing_value")
	R = 0.0
	for row in stock_entry.get("items") or []:
		settlement = row.get(F_SETTLEMENT_AMOUNT)
		if settlement in (None, ""):
			qty = flt(row.transfer_qty if row.transfer_qty not in (None, "") else row.qty)
			rate = flt(row.get(F_ORIGINAL_RATE))
			settlement = flt(qty * rate, precision)
		R += flt(settlement, precision)

	A = flt(stock_entry.total_outgoing_value, precision)
	if not A:
		# Fallback to sum of row amounts
		for row in stock_entry.get("items") or []:
			A += flt(row.amount if row.amount not in (None, "") else row.basic_amount, precision)
		A = flt(A, precision)

	R = flt(R, precision)
	D = flt(A - R, precision)
	return {"receipt_settlement_amount": R, "actual_return_valuation_amount": A, "valuation_difference": D}


def find_active_settlement_je(stock_entry_name: str) -> str | None:
	linked = frappe.db.get_value("Stock Entry", stock_entry_name, F_SETTLEMENT_JE)
	if linked and frappe.db.exists("Journal Entry", linked):
		if frappe.db.get_value("Journal Entry", linked, "docstatus") < 2:
			return linked
	return None


def create_settlement_journal_entry(stock_entry_name: str) -> str:
	"""Create draft Settlement JE. Always draft (locked decision)."""
	se = frappe.get_doc("Stock Entry", stock_entry_name)
	if se.docstatus != 1:
		frappe.throw(_("Consignment Return must be submitted."))
	if not se.get(F_IS_RETURN):
		frappe.throw(_("Stock Entry {0} is not a Consignment Return.").format(se.name))

	existing = find_active_settlement_je(se.name)
	if existing:
		frappe.throw(
			_("Settlement Journal Entry {0} already exists for {1}.").format(existing, se.name)
		)

	amounts = compute_settlement_amounts(se)
	R = amounts["receipt_settlement_amount"]
	A = amounts["actual_return_valuation_amount"]
	D = amounts["valuation_difference"]

	if R <= 0:
		frappe.throw(_("Receipt settlement amount must be greater than zero."))
	if A <= 0:
		frappe.throw(_("Actual return valuation amount must be greater than zero."))

	party_type = se.get(F_PARTY_TYPE)
	party = se.get(F_PARTY)
	party_account = resolve_party_account(party_type, party, se.company)
	temp_account = get_temporary_clearing_account(se.company)
	diff_account = get_valuation_difference_account(se.company)

	# Cost center / finance book: source Stock Entry only — never from Settings
	cost_center = resolve_cost_center_from_stock_entry(se)
	finance_book = resolve_finance_book_from_stock_entry(se)

	je = frappe.new_doc("Journal Entry")
	je.voucher_type = "Journal Entry"
	je.company = se.company
	je.posting_date = se.posting_date or nowdate()
	je.user_remark = _(
		"Consignment Settlement for Return {0}: R={1}, A={2}, D={3}"
	).format(se.name, R, A, D)
	if finance_book and je.meta.has_field("finance_book"):
		je.finance_book = finance_book
	if je.meta.has_field(F_JE_ROLE):
		je.set(F_JE_ROLE, JE_ROLE_SETTLEMENT)

	def _cc(row: dict) -> dict:
		if cost_center and not row.get("cost_center"):
			row["cost_center"] = cost_center
		return row

	# Dr Party R — no Stock Entry reference (avoids Payment Ledger against SE)
	je.append(
		"accounts",
		_cc(
			{
				"account": party_account,
				"party_type": party_type,
				"party": party,
				"debit_in_account_currency": R,
				"credit_in_account_currency": 0,
				"user_remark": _("Settle consignment party at original receipt rate for {0}").format(
					se.name
				),
			}
		),
	)

	# Diff leg
	if D > 0:
		je.append(
			"accounts",
			_cc(
				{
					"account": diff_account,
					"debit_in_account_currency": D,
					"credit_in_account_currency": 0,
					"user_remark": _("Consignment valuation difference (A > R) for {0}").format(se.name),
				}
			),
		)
	elif D < 0:
		je.append(
			"accounts",
			_cc(
				{
					"account": diff_account,
					"debit_in_account_currency": 0,
					"credit_in_account_currency": abs(D),
					"user_remark": _("Consignment valuation difference (A < R) for {0}").format(se.name),
				}
			),
		)

	# Cr Temporary Clearing A
	je.append(
		"accounts",
		_cc(
			{
				"account": temp_account,
				"debit_in_account_currency": 0,
				"credit_in_account_currency": A,
				"user_remark": _("Clear temporary balance at actual return valuation for {0}").format(
					se.name
				),
			}
		),
	)

	je.insert(ignore_permissions=False)
	frappe.db.set_value("Stock Entry", se.name, F_SETTLEMENT_JE, je.name, update_modified=False)
	return je.name
