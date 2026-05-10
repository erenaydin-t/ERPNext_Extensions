# Copyright (c) 2026, Farbod Siyahpoosh and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class PMSettings(Document):
	def validate(self):
		company = self.default_company
		if self.default_bank_account and company:
			acc_company = frappe.db.get_value("Account", self.default_bank_account, "company")
			if acc_company and acc_company != company:
				frappe.throw(
					frappe._("Default Bank Account {0} must belong to company {1}").format(
						self.default_bank_account, company
					)
				)
		if self.default_cost_center and company:
			cc_company = frappe.db.get_value("Cost Center", self.default_cost_center, "company")
			if cc_company and cc_company != company:
				frappe.throw(
					frappe._("Default Cost Center {0} must belong to company {1}").format(
						self.default_cost_center, company
					)
				)
