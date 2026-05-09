# Copyright (c) 2026, Farbod Siyahpoosh and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

PETTY_POSTING_MODE_PAYMENT_ENTRY = "Payment Entry"
PETTY_POSTING_MODE_JOURNAL_ENTRY = "Journal Entry"
PETTY_POSTING_MODE_FALLBACK = "Payment Entry with Journal Entry Fallback"
PETTY_POSTING_MODES = (
	PETTY_POSTING_MODE_PAYMENT_ENTRY,
	PETTY_POSTING_MODE_JOURNAL_ENTRY,
	PETTY_POSTING_MODE_FALLBACK,
)


class PMSettings(Document):
	def validate(self):
		mode = self.petty_cash_payment_posting_mode
		if mode and mode not in PETTY_POSTING_MODES:
			frappe.throw(_("Invalid Petty Cash Payment Posting Mode"))
		company = self.default_company
		for label, acc in (
			("Default Petty Cash Account", self.default_petty_cash_account),
			("Default Payable Account", self.default_payable_account),
			("Default Bank Account", self.default_bank_account),
		):
			if not acc or not company:
				continue
			acc_company = frappe.db.get_value("Account", acc, "company")
			if acc_company and acc_company != company:
				frappe.throw(
					frappe._("{0} {1} must belong to company {2}").format(label, acc, company)
				)
