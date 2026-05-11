# Copyright (c) 2026, Farbod Siyahpoosh and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate, today

from erpnext.accounts.utils import get_balance_on


class PMHolder(Document):
	def autoname(self):
		if not self.employee or not self.company:
			frappe.throw(_("Employee and Company are required before naming"))
		base = f"{self.employee}-{self.company}"
		if len(base) > 120:
			base = base[:120]
		self.name = base

	def validate(self):
		if not self.employee:
			frappe.throw(_("Employee is required"))
		if not self.company:
			frappe.throw(_("Company is required"))
		if not self.petty_cash_account:
			frappe.throw(_("Petty Cash Account is required"))

		self._validate_unique_employee_company()
		self._validate_dedicated_petty_account()

		acc_company = frappe.db.get_value("Account", self.petty_cash_account, "company")
		if acc_company and acc_company != self.company:
			frappe.throw(
				_("Petty Cash Account {0} must belong to company {1}").format(
					self.petty_cash_account, self.company
				)
			)
		self._set_calculated_balances()

	def _validate_unique_employee_company(self):
		filters = {"employee": self.employee, "company": self.company}
		if self.name:
			filters["name"] = ["!=", self.name]
		if frappe.db.exists("PM Holder", filters):
			frappe.throw(
				_("A PM Holder already exists for this employee and company."),
				title=_("Duplicate PM Holder"),
			)

	def _validate_dedicated_petty_account(self):
		"""Each active (non-blocked) holder must use a distinct petty cash account per company."""
		if not self.petty_cash_account or not self.company:
			return
		others = frappe.db.sql(
			"""
			select name from `tabPM Holder`
			where company = %s
				and petty_cash_account = %s
				and ifnull(is_blocked, 0) = 0
				and coalesce(name, '') != coalesce(%s, '')
			limit 1
			""",
			(self.company, self.petty_cash_account, self.name or ""),
		)
		if others:
			frappe.throw(
				_("Each active PM Holder must have a dedicated petty cash account."),
				title=_("Duplicate petty cash account"),
			)

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
						and docstatus = 1
						and ifnull(journal_entry, '') = ''
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
					where employee = %s and company = %s
						and docstatus = 1
						and ifnull(journal_entry, '') != ''
						and ifnull(status, '') != 'Cancelled'
					""",
					(self.employee, self.company),
				)[0][0]
			)
		else:
			self.pending_clearance_amount = 0
			self.consumed_amount = 0
