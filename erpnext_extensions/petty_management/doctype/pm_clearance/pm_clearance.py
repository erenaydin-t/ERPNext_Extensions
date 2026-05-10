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
		self.je_clearance_date = getdate(self.transaction_date or today())
		self._sync_holder_and_pending()
		self._stamp_rows()
		self._validate_duplicate_purchase_invoices()
		self._validate_and_stamp_pi_rows()
		self._calc_line_totals()
		self._calc_parent_totals()
		self._sync_clearance_status_from_workflow()
		self._sync_funding_traceability_snapshot()
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
		# Submit represents "request for settlement"; settlement JE is created later via "Settle Petty Cash".
		# Workflow (Draft → Pending Finance Review → Approved) is for approvals only.
		return

	def on_submit(self):
		# No JE on submit. Persist status aligned with workflow after submit (workflow may update state).
		refreshed = frappe.get_doc("PM Clearance", self.name)
		refreshed._sync_clearance_status_from_workflow()
		if refreshed.status:
			frappe.db.set_value(
				"PM Clearance",
				self.name,
				"status",
				refreshed.status,
				update_modified=False,
			)

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

	def _sync_funding_traceability_snapshot(self):
		"""UX-only snapshot for Funding / Traceability (no change to settlement accounting)."""
		self.current_petty_balance = flt(self.pending_amount)
		if not self.holder:
			return
		hb = frappe.db.get_value(
			"PM Holder",
			self.holder,
			["current_balance", "consumed_amount"],
			as_dict=True,
		)
		if not hb:
			return
		self.total_cleared_amount = flt(hb.consumed_amount)
		self.total_funded_amount = flt(hb.current_balance) + flt(hb.consumed_amount)

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
		# Settlement is not a workflow action: once JE is created, status becomes Settled regardless of workflow_state.
		if self.journal_entry:
			self.status = "Settled"
			return

		ws = self.workflow_state
		if not ws:
			return
		ws_title = frappe.db.get_value("Workflow State", ws, "workflow_state_name") or ws
		m = {
			"Draft": "Draft",
			"Pending Finance Review": "Pending Finance Review",
			"Approved": "Approved",
			"Rejected": "Cancelled",
		}
		if ws_title in m:
			self.status = m[ws_title]

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
def settle_petty_cash(pm_clearance: str) -> str:
	"""Create settlement Journal Entry after workflow approval.

	This is a UX/business action, not a workflow transition:
	- Requires submitted PM Clearance + workflow Approved.
	- Creates the Journal Entry, links it, marks status Settled.
	- Stamps Purchase Invoice traceability custom fields if they exist and are empty.
	"""
	doc = frappe.get_doc("PM Clearance", pm_clearance)
	if not frappe.has_permission("PM Clearance", "read", doc=doc):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	doc.check_permission("submit")
	if doc.docstatus != 1:
		frappe.throw(_("Please submit PM Clearance before settling."), title=_("Submit required"))

	ws_title = None
	if doc.workflow_state:
		ws_title = frappe.db.get_value("Workflow State", doc.workflow_state, "workflow_state_name")
	if ws_title != "Approved":
		frappe.throw(_("Settle is only allowed when Workflow State is Approved."), title=_("Approval required"))

	if doc.journal_entry:
		frappe.throw(_("Settlement Journal Entry already exists: {0}").format(doc.journal_entry))

	je = doc._create_clearance_journal_entry()
	doc.db_set("journal_entry", je.name, update_modified=False)
	doc.db_set("status", "Settled", update_modified=False)

	# Link back to child rows
	for row in doc.details:
		frappe.db.set_value(
			row.doctype,
			row.name,
			{"generated_doctype": "Journal Entry", "generated_document": je.name},
			update_modified=False,
		)

	# Purchase Invoice traceability fields (only set if fields exist and target is empty)
	meta_pi = frappe.get_meta("Purchase Invoice")
	has_holder = meta_pi.has_field("custom_pm_holder")
	has_clearance = meta_pi.has_field("custom_pm_clearance")
	if has_holder or has_clearance:
		for row in doc.details:
			if not row.purchase_invoice:
				continue
			updates = {}
			if has_holder:
				cur = frappe.db.get_value("Purchase Invoice", row.purchase_invoice, "custom_pm_holder")
				if not cur and doc.holder:
					updates["custom_pm_holder"] = doc.holder
			if has_clearance:
				cur = frappe.db.get_value("Purchase Invoice", row.purchase_invoice, "custom_pm_clearance")
				if not cur:
					updates["custom_pm_clearance"] = doc.name
			if updates:
				frappe.db.set_value("Purchase Invoice", row.purchase_invoice, updates, update_modified=False)

	return je.name
