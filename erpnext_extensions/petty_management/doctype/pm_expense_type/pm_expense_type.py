# Copyright (c) 2026, Farbod Siyahpoosh and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class PMExpenseType(Document):
	def validate(self):
		if self.disabled:
			return
		if not self.expense_type_name:
			frappe.throw(frappe._("Expense Type Name is required"))
		if self.company and self.expense_account:
			acc_company = frappe.db.get_value("Account", self.expense_account, "company")
			if acc_company and acc_company != self.company:
				frappe.throw(
					frappe._("Expense Account {0} must belong to company {1}").format(
						self.expense_account, self.company
					)
				)
		if self.company and self.tax_account:
			acc_company = frappe.db.get_value("Account", self.tax_account, "company")
			if acc_company and acc_company != self.company:
				frappe.throw(
					frappe._("Tax Account {0} must belong to company {1}").format(
						self.tax_account, self.company
					)
				)
