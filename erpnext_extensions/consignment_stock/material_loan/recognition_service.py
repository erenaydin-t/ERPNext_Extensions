# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt, nowdate

from erpnext_extensions.consignment_stock.accounting import (
	resolve_cost_center_from_stock_entry,
	resolve_finance_book_from_stock_entry,
)
from erpnext_extensions.consignment_stock.material_loan.accounting import get_temporary_clearing_account
from erpnext_extensions.consignment_stock.material_loan.constants import (
	F_IS_LOAN_ISSUE,
	F_JE_ROLE,
	F_PARTY,
	F_PARTY_TYPE,
	F_RECOGNITION_JE,
	JE_ROLE_RECOGNITION,
)
from erpnext_extensions.consignment_stock.material_loan.frozen_valuation import (
	get_issue_total_frozen_value,
)
from erpnext_extensions.consignment_stock.material_loan.party_account import (
	resolve_material_loan_party_account,
	validate_party_for_tracking,
)


def find_active_recognition_je(stock_entry_name: str) -> str | None:
	linked = frappe.db.get_value("Stock Entry", stock_entry_name, F_RECOGNITION_JE)
	if linked and frappe.db.exists("Journal Entry", linked):
		if frappe.db.get_value("Journal Entry", linked, "docstatus") < 2:
			return linked
	return None


def create_recognition_journal_entry(stock_entry_name: str) -> str:
	se = frappe.get_doc("Stock Entry", stock_entry_name)
	if se.docstatus != 1:
		frappe.throw(_("Material Loan Issue must be submitted."))
	if not se.get(F_IS_LOAN_ISSUE):
		frappe.throw(_("Stock Entry {0} is not a Material Loan Issue.").format(se.name))

	existing = find_active_recognition_je(se.name)
	if existing:
		frappe.throw(
			_("Material Loan Recognition Journal Entry {0} already exists for {1}.").format(
				existing, se.name
			)
		)

	party_type = se.get(F_PARTY_TYPE)
	party = se.get(F_PARTY)
	validate_party_for_tracking(party_type, party)
	party_account = resolve_material_loan_party_account(party_type, se.company)
	temp_account = get_temporary_clearing_account(se.company)
	amount = get_issue_total_frozen_value(se)
	if amount <= 0:
		frappe.throw(_("Material Loan Issue value must be greater than zero."))

	cost_center = resolve_cost_center_from_stock_entry(se)
	finance_book = resolve_finance_book_from_stock_entry(se)

	je = frappe.new_doc("Journal Entry")
	je.voucher_type = "Journal Entry"
	je.company = se.company
	je.posting_date = se.posting_date or nowdate()
	je.user_remark = _("Material Loan Recognition for Stock Entry {0}").format(se.name)
	if finance_book and je.meta.has_field("finance_book"):
		je.finance_book = finance_book
	if je.meta.has_field(F_JE_ROLE):
		je.set(F_JE_ROLE, JE_ROLE_RECOGNITION)

	party_row = {
		"account": party_account,
		"party_type": party_type,
		"party": party,
		"debit_in_account_currency": amount,
		"credit_in_account_currency": 0,
		"user_remark": _("Recognize Material Loan party balance for {0}").format(se.name),
	}
	temp_row = {
		"account": temp_account,
		"debit_in_account_currency": 0,
		"credit_in_account_currency": amount,
		"user_remark": _("Clear Material Loan temporary balance for {0}").format(se.name),
	}
	if cost_center:
		party_row["cost_center"] = cost_center
		temp_row["cost_center"] = cost_center

	# No reference_type=Stock Entry on any JE line (PLE-safe).
	je.append("accounts", party_row)
	je.append("accounts", temp_row)
	je.insert(ignore_permissions=False)
	frappe.db.set_value("Stock Entry", se.name, F_RECOGNITION_JE, je.name, update_modified=False)

	from erpnext_extensions.consignment_stock.material_loan import status as ml_status

	ml_status.refresh_issue_statuses(se.name)
	return je.name
