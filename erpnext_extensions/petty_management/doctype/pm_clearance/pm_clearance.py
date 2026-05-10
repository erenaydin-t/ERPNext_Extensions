# Copyright (c) 2026, Farbod Siyahpoosh and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.model.naming import getseries
from frappe.utils import flt, getdate, today

from erpnext.accounts.utils import get_balance_on

from erpnext_extensions.petty_management.utils import (
	get_pm_holder_name,
	get_pm_settings,
	petty_clearance_requires_workflow_approval,
)


class PMClearance(Document):
	"""Settles Purchase Invoices via Journal Entry against the holder Petty Cash Account (no direct PM Request link)."""

	def autoname(self):
		if not self.employee:
			frappe.throw(_("Employee is required before naming"))
		d = getdate(self.transaction_date or today())
		emp_key = str(self.employee).replace(" ", "")[:40]
		prefix = f"CLR-{emp_key}-{d.year}-{d.month:02d}-"
		self.name = prefix + getseries(prefix, 5)

	def validate(self):
		self._sync_holder_and_pending()
		self._stamp_rows()
		self._validate_duplicate_purchase_invoices()
		self._validate_and_stamp_pi_rows()
		self._calc_line_totals()
		self._calc_parent_totals()
		self._sync_clearance_status_from_workflow()
		settings = get_pm_settings()

		if not self.details:
			frappe.throw(_("Add at least one Purchase Invoice line"))

		if flt(self.total_expense_amount) <= 0:
			frappe.throw(_("Total settlement amount must be greater than zero"))

		allow_neg = bool(settings and settings.allow_negative_balance)
		if not allow_neg and flt(self.total_expense_amount) > flt(self.pending_amount) + 1e-6:
			frappe.throw(
				_("Clearance total {0} exceeds pending petty cash {1}.").format(
					self.total_expense_amount, self.pending_amount
				)
			)

		for row in self.details:
			if settings and settings.require_attachment and not row.proof:
				frappe.throw(_("Row {0}: attachment is required by PM Settings").format(row.idx))
			if settings and settings.require_bill_no and not row.bill_no:
				frappe.throw(_("Row {0}: bill number is required by PM Settings").format(row.idx))

	def before_submit(self):
		if not petty_clearance_requires_workflow_approval():
			return
		if not self.workflow_state:
			frappe.throw(
				_("Workflow State is required before submit."),
				title=_("Approval required"),
			)
		ws_title = frappe.db.get_value("Workflow State", self.workflow_state, "workflow_state_name")
		if ws_title != "Approved":
			frappe.throw(
				_("Submit is only allowed when Workflow State is Approved."),
				title=_("Approval required"),
			)

	def on_submit(self):
		settings = get_pm_settings()
		je = self._create_clearance_journal_entry()
		self.db_set("journal_entry", je.name, update_modified=False)
		for row in self.details:
			frappe.db.set_value(
				row.doctype,
				row.name,
				{"generated_doctype": "Journal Entry", "generated_document": je.name},
				update_modified=False,
			)

		self.db_set("status", "Submitted", update_modified=False)
		posted = frappe.db.get_value("Workflow State", {"workflow_state_name": "Posted"}, "name")
		if posted:
			self.db_set("workflow_state", posted, update_modified=False)

	def before_cancel(self):
		if self.journal_entry:
			try:
				je = frappe.get_doc("Journal Entry", self.journal_entry)
				if je.docstatus == 1:
					je.cancel()
			except frappe.ValidationError:
				frappe.throw(
					_("Could not cancel linked Journal Entry {0}. Cancel or amend it first.").format(
						self.journal_entry
					)
				)

	def on_cancel(self):
		frappe.db.set_value(
			"PM Clearance",
			self.name,
			{
				"journal_entry": None,
				"purchase_invoice": None,
				"status": "Cancelled",
			},
			update_modified=False,
		)
		for row_name in frappe.get_all(
			"PM Clearance Detail",
			filters={"parent": self.name, "parenttype": "PM Clearance"},
			pluck="name",
		):
			frappe.db.set_value(
				"PM Clearance Detail",
				row_name,
				{
					"generated_doctype": None,
					"generated_document": None,
				},
				update_modified=False,
			)

	def _sync_holder_and_pending(self):
		hname = get_pm_holder_name(self.employee, self.company)
		self.holder = hname
		if not self.holder:
			frappe.throw(_("No PM Holder found for this employee and company"))
		holder = frappe.get_doc("PM Holder", self.holder)
		self.petty_cash_account = holder.petty_cash_account
		as_on = getdate(self.transaction_date or today())
		self.pending_amount = flt(
			get_balance_on(
				account=self.petty_cash_account,
				date=as_on,
				company=self.company,
			)
		)

	def _stamp_rows(self):
		for row in self.details:
			if not row.created_by_user:
				row.created_by_user = frappe.session.user

	def _validate_duplicate_purchase_invoices(self):
		seen = set()
		for row in self.details:
			if not row.purchase_invoice:
				continue
			if row.purchase_invoice in seen:
				frappe.throw(
					_("Purchase Invoice {0} cannot appear on more than one line.").format(row.purchase_invoice),
					title=_("Duplicate Purchase Invoice"),
				)
			seen.add(row.purchase_invoice)

	def _validate_and_stamp_pi_rows(self):
		for row in self.details:
			if not row.purchase_invoice:
				frappe.throw(_("Row {0}: Purchase Invoice is required.").format(row.idx))
			if row.reference_doctype and row.reference_doctype != "Purchase Invoice":
				frappe.throw(
					_("Line {0}: only Purchase Invoice is supported as settlement reference.").format(row.idx),
				)
			row.reference_doctype = "Purchase Invoice"
			pi = frappe.get_doc("Purchase Invoice", row.purchase_invoice)
			if pi.docstatus != 1:
				frappe.throw(_("Row {0}: Purchase Invoice must be submitted.").format(row.idx))
			if pi.company != self.company:
				frappe.throw(
					_("Row {0}: Purchase Invoice belongs to another company.").format(row.idx),
				)
			if flt(pi.outstanding_amount) <= 0:
				frappe.throw(
					_("Row {0}: Purchase Invoice has no outstanding amount to settle.").format(row.idx),
				)
			row.supplier = pi.supplier
			row.outstanding_amount = flt(pi.outstanding_amount)
			if flt(row.allocated_amount) <= 0:
				row.allocated_amount = flt(pi.outstanding_amount)
			if flt(row.allocated_amount) <= 0:
				frappe.throw(_("Row {0}: Allocated Amount must be greater than zero.").format(row.idx))
			if flt(row.allocated_amount) > flt(pi.outstanding_amount) + 1e-6:
				frappe.throw(
					_("Row {0}: allocated amount cannot exceed Purchase Invoice outstanding ({1}).").format(
						row.idx, pi.outstanding_amount
					),
				)

	def _calc_line_totals(self):
		for row in self.details:
			row.amount_plus_tax = flt(row.allocated_amount)

	def _calc_parent_totals(self):
		total = 0.0
		for row in self.details:
			total += flt(row.allocated_amount)
		self.total_expense_without_tax = 0
		self.total_tax_amount = 0
		self.total_expense_amount = total
		self.total_petty_cash = total
		self.remaining_amount = flt(self.pending_amount) - flt(self.total_expense_amount)

	def _sync_clearance_status_from_workflow(self):
		ws = self.workflow_state
		if not ws:
			return
		ws_title = frappe.db.get_value("Workflow State", ws, "workflow_state_name") or ws
		if ws_title == "Rejected":
			self.status = "Cancelled"

	def _create_clearance_journal_entry(self):
		"""Journal Entry: Dr Purchase Invoice credit_to (Supplier + PI ref), Cr petty cash — PI-only settlement."""
		settings = get_pm_settings()
		je = frappe.new_doc("Journal Entry")
		je.company = self.company
		je.posting_date = getdate(self.je_clearance_date or self.transaction_date or today())
		je.user_remark = _("Petty cash clearance {0}").format(self.name)

		meta = frappe.get_meta("Journal Entry")
		if meta.has_field("custom_pm_clearance"):
			je.custom_pm_clearance = self.name
		if meta.has_field("custom_pm_holder") and self.holder:
			je.custom_pm_holder = self.holder

		total_petty_credit = 0.0

		for row in self.details:
			pi = frappe.get_doc("Purchase Invoice", row.purchase_invoice)
			alloc = flt(row.allocated_amount)
			cc = row.cost_center or None
			prj = row.project or self.project or None
			line = {
				"account": pi.credit_to,
				"party_type": "Supplier",
				"party": pi.supplier,
				"reference_type": "Purchase Invoice",
				"reference_name": pi.name,
				"debit_in_account_currency": alloc,
				"credit_in_account_currency": 0,
			}
			if cc:
				line["cost_center"] = cc
			if prj:
				line["project"] = prj
			je.append("accounts", line)
			total_petty_credit += alloc

		je.append(
			"accounts",
			{
				"account": self.petty_cash_account,
				"debit_in_account_currency": 0,
				"credit_in_account_currency": total_petty_credit,
			},
		)

		je.insert(ignore_permissions=True)
		if settings and settings.auto_submit_journal_entry:
			je.submit()
		return je


@frappe.whitelist()
def create_journal_entry(pm_clearance: str):
	"""Submit the clearance if still draft; one Journal Entry is created on submit."""
	doc = frappe.get_doc("PM Clearance", pm_clearance)
	doc.check_permission("submit")
	if doc.docstatus == 1:
		frappe.throw(_("Already submitted"))
	doc.submit()
	doc.reload()
	return doc.journal_entry
