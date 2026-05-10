# Copyright (c) 2026, Farbod Siyahpoosh and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.model.naming import getseries
from frappe.utils import flt, getdate, today

from erpnext.accounts.utils import get_balance_on

from erpnext_extensions.petty_management.utils import (
	employee_has_draft_pm_clearance,
	get_pm_holder_name,
	get_pm_settings,
)


class PMRequest(Document):
	def autoname(self):
		if not self.employee:
			frappe.throw(_("Employee is required before naming"))
		d = getdate(self.transaction_date or today())
		emp_key = str(self.employee).replace(" ", "")[:40]
		prefix = f"REQ-{emp_key}-{d.year}-{d.month:02d}-"
		self.name = prefix + getseries(prefix, 5)

	def validate(self):
		self._sync_holder_and_balances()
		self._compute_totals()
		self._sync_status_from_workflow()
		settings = get_pm_settings()
		if not self.details:
			frappe.throw(_("Add at least one detail line"))
		if flt(self.total_requested_amount) <= 0:
			frappe.throw(_("Total Requested Amount must be greater than zero"))

		holder_doc = None
		if self.holder:
			holder_doc = frappe.get_doc("PM Holder", self.holder)
			if holder_doc.is_blocked:
				frappe.throw(_("This petty cash holder is blocked"))
			if (
				settings
				and settings.block_new_request_if_pending_clearance
				and employee_has_draft_pm_clearance(self.employee, self.company)
			):
				frappe.throw(
					_("This employee has a pending PM Clearance; new requests are blocked by settings.")
				)

		if holder_doc and holder_doc.get("max_balance") is not None:
			limit = flt(holder_doc.max_balance)
			projected = flt(self.previous_balance) + flt(self.total_requested_amount)
			allow_over = bool(settings and settings.allow_negative_balance)
			if not allow_over and projected > limit + 1e-6:
				frappe.throw(
					_("Advance would exceed max balance {0} (projected {1}).").format(limit, projected)
				)

		self._validate_payment_accounts()

	def _validate_payment_accounts(self):
		if not self.paid_from_account:
			frappe.throw(_("Please select Paid From Account on PM Request."))
		if not self.petty_cash_account:
			return
		if self.paid_from_account == self.petty_cash_account:
			frappe.throw(_("Paid From Account cannot be the same as Petty Cash Account"))
		for label, acc in (
			("Paid From Account", self.paid_from_account),
			("Petty Cash Account", self.petty_cash_account),
		):
			acc_company = frappe.db.get_value("Account", acc, "company")
			if acc_company and acc_company != self.company:
				frappe.throw(_("{0} must belong to company {1}").format(label, self.company))
		acc_type = frappe.db.get_value("Account", self.paid_from_account, "account_type")
		if acc_type and acc_type not in ("Bank", "Cash"):
			frappe.throw(_("Paid From Account must be a Bank or Cash account"))
		if self.employee_bank_account:
			ba = frappe.db.get_value(
				"Bank Account",
				self.employee_bank_account,
				["party_type", "party", "company"],
				as_dict=True,
			)
			if ba:
				if ba.get("company") and ba["company"] != self.company:
					frappe.throw(_("Employee Bank Account must belong to the same company as this request"))
				if ba.get("party_type") == "Employee" and ba.get("party") and ba["party"] != self.employee:
					frappe.throw(_("Employee Bank Account must be for this request's employee"))

	def _sync_holder_and_balances(self):
		hname = get_pm_holder_name(self.employee, self.company)
		self.holder = hname
		if not self.holder:
			frappe.throw(_("No PM Holder found for this employee and company"))
		holder = frappe.get_doc("PM Holder", self.holder)
		self.petty_cash_account = holder.petty_cash_account
		self.max_balance_for_petty_cash = holder.max_balance
		as_on = getdate(self.transaction_date or today())
		self.previous_balance = flt(
			get_balance_on(
				account=self.petty_cash_account,
				date=as_on,
				company=self.company,
			)
		)

	def _compute_totals(self):
		total = 0
		for row in self.details:
			total += flt(row.advance_amount)
		self.total_requested_amount = total
		for row in self.details:
			row.percent_of_total = (flt(row.advance_amount) / total * 100) if total else 0

	def _sync_status_from_workflow(self):
		ws = self.workflow_state
		if not ws:
			return
		ws_title = frappe.db.get_value("Workflow State", ws, "workflow_state_name") or ws
		m = {
			"Draft": "Draft",
			"Pending Approval": "Pending",
			"Approved": "Approved",
			"Rejected": "Rejected",
			"Paid": "Paid",
			"Cancelled": "Cancelled",
		}
		if ws_title in m:
			self.status = m[ws_title]

	def before_cancel(self):
		if self.payment_entry and frappe.db.get_value("Payment Entry", self.payment_entry, "docstatus") == 1:
			frappe.throw(_("Cancel the linked Payment Entry first"))
		if self.journal_entry and frappe.db.get_value("Journal Entry", self.journal_entry, "docstatus") == 1:
			frappe.throw(_("Cancel the linked Journal Entry first"))


@frappe.whitelist()
def create_payment_entry(pm_request: str):
	doc = frappe.get_doc("PM Request", pm_request)
	if not frappe.has_permission("PM Request", "read", doc=doc):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	if doc.docstatus != 1:
		frappe.throw(_("Please submit PM Request before creating Payment Entry."))
	if not frappe.has_permission("PM Request", "submit", doc=doc):
		frappe.throw(_("Not permitted to create Payment Entry"), frappe.PermissionError)

	settings = get_pm_settings()
	ws_title = None
	if doc.workflow_state:
		ws_title = frappe.db.get_value("Workflow State", doc.workflow_state, "workflow_state_name")
	approved = (doc.status or "") == "Approved" or ws_title == "Approved"
	if not approved:
		frappe.throw(_("Payment can only be created when the request is Approved"))

	if doc.payment_entry or (doc.payment_status or "") == "Paid":
		frappe.throw(_("Payment Entry already exists or this request is already marked Paid"))

	if not doc.petty_cash_account:
		frappe.throw(_("Petty Cash Account is missing"))

	if not doc.paid_from_account:
		frappe.throw(_("Please select Paid From Account on PM Request."))

	paid_from = doc.paid_from_account

	amount = flt(doc.total_requested_amount)
	if amount <= 0:
		frappe.throw(_("Total Requested Amount must be positive"))

	company_currency = frappe.db.get_value("Company", doc.company, "default_currency")

	def _mark_doc_paid(link_field: str, link_name: str):
		doc.db_set(link_field, link_name, update_modified=False)
		doc.db_set("payment_status", "Paid", update_modified=False)
		doc.db_set("status", "Paid", update_modified=False)
		paid_state = frappe.db.get_value("Workflow State", {"workflow_state_name": "Paid"}, "name")
		if paid_state:
			doc.db_set("workflow_state", paid_state, update_modified=False)

	pe = frappe.new_doc("Payment Entry")
	pe.payment_type = "Pay"
	pe.company = doc.company
	pe.posting_date = doc.transaction_date or today()
	pe.party_type = "Employee"
	pe.party = doc.employee
	pe.paid_from = paid_from
	pe.paid_to = doc.petty_cash_account
	pe.paid_amount = amount
	pe.received_amount = amount
	pe.target_exchange_rate = 1
	pe.source_exchange_rate = 1
	if company_currency:
		pe.paid_to_account_currency = company_currency
		pe.paid_from_account_currency = company_currency
	pe.reference_no = doc.name
	pe.reference_date = getdate(doc.transaction_date) if doc.transaction_date else pe.posting_date
	remarks = _("Petty cash advance for {0}").format(doc.name)

	meta_pe = frappe.get_meta("Payment Entry")
	if doc.employee_bank_account:
		if meta_pe.has_field("party_bank_account"):
			pe.party_bank_account = doc.employee_bank_account
		else:
			ba_ref = frappe.db.get_value("Bank Account", doc.employee_bank_account, "account_name") or str(
				doc.employee_bank_account
			)
			remarks += "\n" + _("Employee Bank Account: {0}").format(ba_ref)
	pe.remarks = remarks

	if meta_pe.has_field("custom_pm_request"):
		pe.custom_pm_request = doc.name
	if meta_pe.has_field("custom_pm_holder") and doc.holder:
		pe.custom_pm_holder = doc.holder

	try:
		pe.insert(ignore_permissions=True)
		if settings and settings.auto_submit_payment_entry:
			pe.submit()
	except Exception as e:
		frappe.db.rollback()
		frappe.throw(
			_("Payment Entry could not be created: {0}").format(str(e)),
			title=_("Payment Entry failed"),
		)

	_mark_doc_paid("payment_entry", pe.name)
	return pe.name
