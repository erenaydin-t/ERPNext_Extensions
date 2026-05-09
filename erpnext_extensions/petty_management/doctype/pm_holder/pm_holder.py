# Copyright (c) 2026, Farbod Siyahpoosh and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import flt, getdate, today

from erpnext.accounts.utils import get_balance_on


class PMHolder(Document):
	def validate(self):
		if not self.employee:
			frappe.throw(frappe._("Employee is required"))
		if not self.petty_cash_account:
			frappe.throw(frappe._("Petty Cash Account is required"))
		acc_company = frappe.db.get_value("Account", self.petty_cash_account, "company")
		if acc_company and acc_company != self.company:
			frappe.throw(
				frappe._("Petty Cash Account {0} must belong to company {1}").format(
					self.petty_cash_account, self.company
				)
			)
		self._set_calculated_balances()

	def _set_calculated_balances(self):
		as_on = getdate(today())
		self.current_balance = flt(
			get_balance_on(
				account=self.petty_cash_account,
				date=as_on,
				company=self.company,
			)
		)
		if frappe.db.has_table("tabPM Clearance"):
			self.pending_clearance_amount = flt(
				frappe.db.sql(
					"""
					select coalesce(sum(total_expense_amount), 0)
					from `tabPM Clearance`
					where employee = %s and company = %s
						and docstatus = 0
						and ifnull(status, '') != 'Cancelled'
					""",
					(self.employee, self.company),
				)[0][0]
			)
			self.consumed_amount = flt(
				frappe.db.sql(
					"""
					select coalesce(sum(total_expense_amount), 0)
					from `tabPM Clearance`
					where employee = %s and company = %s and docstatus = 1
					""",
					(self.employee, self.company),
				)[0][0]
			)
		else:
			self.pending_clearance_amount = 0
			self.consumed_amount = 0
