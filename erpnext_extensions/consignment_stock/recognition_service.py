# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt, nowdate

from erpnext_extensions.consignment_stock.accounting import (
	get_consignment_settings,
	get_temporary_clearing_account,
)
from erpnext_extensions.consignment_stock.constants import (
	F_IS_RECEIPT,
	F_JE_ROLE,
	F_PARTY,
	F_PARTY_TYPE,
	F_RECOGNITION_JE,
	JE_ROLE_RECOGNITION,
)
from erpnext_extensions.consignment_stock.party import resolve_party_account


def get_receipt_value(stock_entry) -> float:
	total = 0.0
	for row in stock_entry.get("items") or []:
		total += flt(row.amount if row.amount not in (None, "") else row.basic_amount)
	return flt(total, stock_entry.precision("total_incoming_value"))


def find_active_recognition_je(stock_entry_name: str) -> str | None:
	linked = frappe.db.get_value("Stock Entry", stock_entry_name, F_RECOGNITION_JE)
	if linked and frappe.db.exists("Journal Entry", linked):
		if frappe.db.get_value("Journal Entry", linked, "docstatus") < 2:
			return linked

	# Fallback search by role + reference
	rows = frappe.get_all(
		"Journal Entry",
		filters={F_JE_ROLE: JE_ROLE_RECOGNITION, "docstatus": ("<", 2)},
		fields=["name", "user_remark"],
		limit=50,
	)
	for row in rows:
		if stock_entry_name in (row.user_remark or ""):
			return row.name
	return None


def create_recognition_journal_entry(stock_entry_name: str) -> str:
	"""Create draft Recognition JE. Always draft (locked decision)."""
	se = frappe.get_doc("Stock Entry", stock_entry_name)
	if se.docstatus != 1:
		frappe.throw(_("Consignment Receipt must be submitted."))
	if not se.get(F_IS_RECEIPT):
		frappe.throw(_("Stock Entry {0} is not a Consignment Receipt.").format(se.name))

	existing = find_active_recognition_je(se.name)
	if existing:
		frappe.throw(
			_("Recognition Journal Entry {0} already exists for {1}.").format(existing, se.name)
		)

	settings = get_consignment_settings(se.company)
	temp_account = get_temporary_clearing_account(se.company)
	party_type = se.get(F_PARTY_TYPE)
	party = se.get(F_PARTY)
	party_account = resolve_party_account(party_type, party, se.company)
	amount = get_receipt_value(se)
	if amount <= 0:
		frappe.throw(_("Consignment Receipt value must be greater than zero."))

	cost_center = settings.default_cost_center
	je = frappe.new_doc("Journal Entry")
	je.voucher_type = "Journal Entry"
	je.company = se.company
	je.posting_date = se.posting_date or nowdate()
	je.user_remark = _("Consignment Recognition for Stock Entry {0}").format(se.name)
	if settings.default_finance_book and je.meta.has_field("finance_book"):
		je.finance_book = settings.default_finance_book
	if je.meta.has_field(F_JE_ROLE):
		je.set(F_JE_ROLE, JE_ROLE_RECOGNITION)

	# Dr Temporary Clearing (no Stock Entry reference on JE lines — see review note on PLE)
	temp_row = {
		"account": temp_account,
		"debit_in_account_currency": amount,
		"credit_in_account_currency": 0,
		"user_remark": _("Clear consignment temporary balance for {0}").format(se.name),
	}
	if cost_center:
		temp_row["cost_center"] = cost_center
	je.append("accounts", temp_row)

	# Cr Party — do not set reference_type/reference_name to Stock Entry:
	# ERPNext creates Payment Ledger Entry against_voucher=Stock Entry which blocks SE cancel.
	party_row = {
		"account": party_account,
		"party_type": party_type,
		"party": party,
		"debit_in_account_currency": 0,
		"credit_in_account_currency": amount,
		"user_remark": _("Recognize consignment party balance for {0}").format(se.name),
	}
	if cost_center:
		party_row["cost_center"] = cost_center
	je.append("accounts", party_row)

	je.insert(ignore_permissions=False)
	# Link on SE
	frappe.db.set_value("Stock Entry", se.name, F_RECOGNITION_JE, je.name, update_modified=False)
	return je.name
