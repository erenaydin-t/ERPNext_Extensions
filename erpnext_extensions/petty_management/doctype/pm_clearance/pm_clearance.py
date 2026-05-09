# Copyright (c) 2026, Farbod Siyahpoosh and contributors
# For license information, please see license.txt

from collections import defaultdict

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
		self._apply_expense_type_defaults()
		self._calc_line_totals()
		self._validate_duplicate_purchase_invoices()
		self._validate_and_stamp_pi_rows()
		self._calc_parent_totals()
		self._sync_clearance_status_from_workflow()
		settings = get_pm_settings()

		if not self.details:
			frappe.throw(_("Add at least one expense line"))

		if flt(self.total_expense_amount) <= 0:
			frappe.throw(_("Total Expense Amount must be greater than zero"))

		allow_neg = bool(settings and settings.allow_negative_balance)
		if not allow_neg and flt(self.total_expense_amount) > flt(self.pending_amount) + 1e-6:
			frappe.throw(
				_("Clearance total {0} exceeds pending petty cash {1}.").format(
					self.total_expense_amount, self.pending_amount
				)
			)

		for row in self.details:
			if not row.is_non_stock_expense_type:
				frappe.throw(
					_("Line {0}: stock / asset clearance is not supported in this version").format(row.idx)
				)
			et = frappe.get_cached_doc("PM Expense Type", row.expense_type)
			if et.company and et.company != self.company:
				frappe.throw(
					_("Line {0}: Expense Type {1} belongs to another company").format(row.idx, row.expense_type)
				)
			if et.disabled:
				frappe.throw(_("Expense Type {0} is disabled").format(row.expense_type))
			if settings and settings.require_attachment and not row.proof:
				frappe.throw(_("Row {0}: attachment is required by PM Settings").format(row.idx))
			if et.requires_attachment and not row.proof:
				frappe.throw(_("Row {0}: attachment is required for this expense type").format(row.idx))
			if settings and settings.require_supplier and not row.supplier:
				frappe.throw(_("Row {0}: supplier is required by PM Settings").format(row.idx))
			if et.requires_supplier and not row.supplier:
				frappe.throw(_("Row {0}: supplier is required for this expense type").format(row.idx))
			if settings and settings.require_bill_no and not row.bill_no:
				frappe.throw(_("Row {0}: bill number is required by PM Settings").format(row.idx))
			if settings and flt(settings.max_single_expense_amount) > 0:
				if flt(row.amount_plus_tax) > flt(settings.max_single_expense_amount):
					frappe.throw(
						_("Row {0}: exceeds max single expense amount").format(row.idx),
					)
			if flt(row.tax_amount) and not et.tax_account:
				pass

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
			if row.reference_doctype and row.reference_doctype != "Purchase Invoice":
				frappe.throw(
					_("Line {0}: only Purchase Invoice is supported as settlement reference.").format(row.idx),
				)
			if row.purchase_invoice:
				row.reference_doctype = "Purchase Invoice"
				pi = frappe.get_doc("Purchase Invoice", row.purchase_invoice)
				if pi.docstatus != 1:
					frappe.throw(_("Row {0}: Purchase Invoice must be submitted.").format(row.idx))
				if pi.company != self.company:
					frappe.throw(
						_("Line {0}: Purchase Invoice belongs to another company.").format(row.idx),
					)
				if flt(pi.outstanding_amount) <= 0:
					frappe.throw(
						_("Line {0}: Purchase Invoice has no outstanding amount to settle.").format(row.idx),
					)
				row.party_type = "Supplier"
				row.party = pi.supplier
				row.supplier = pi.supplier
				row.outstanding_amount = flt(pi.outstanding_amount)
				if not row.allocated_amount:
					row.allocated_amount = row.amount_plus_tax or row.amount
				if flt(row.allocated_amount) <= 0:
					frappe.throw(_("Row {0}: Allocated Amount must be greater than zero.").format(row.idx))
				if flt(row.allocated_amount) > flt(pi.outstanding_amount) + 1e-6:
					frappe.throw(
						_("Row {0}: allocated amount cannot exceed Purchase Invoice outstanding ({1}).").format(
							row.idx, pi.outstanding_amount
						),
					)
			elif row.reference_doctype:
				frappe.throw(_("Line {0}: set Purchase Invoice or clear Reference DocType.").format(row.idx))

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

	def _apply_expense_type_defaults(self):
		for row in self.details:
			if not row.expense_type:
				continue
			et = frappe.get_cached_doc("PM Expense Type", row.expense_type)
			row.is_tax_applicable = 1 if et.is_tax_applicable else 0
			row.is_non_stock_expense_type = 1 if et.is_non_stock_expense_type else 0
			if not row.cost_center and et.default_cost_center:
				row.cost_center = et.default_cost_center
			if not row.project and self.project:
				row.project = self.project

	def _calc_line_totals(self):
		for row in self.details:
			row.amount_plus_tax = flt(row.amount) + flt(row.tax_amount)

	def _calc_parent_totals(self):
		t_net = 0
		t_tax = 0
		for row in self.details:
			t_net += flt(row.amount)
			t_tax += flt(row.tax_amount)
		self.total_expense_without_tax = t_net
		self.total_tax_amount = t_tax
		self.total_expense_amount = t_net + t_tax
		self.total_petty_cash = self.total_expense_amount
		self.remaining_amount = flt(self.pending_amount) - flt(self.total_expense_amount)

	def _sync_clearance_status_from_workflow(self):
		ws = self.workflow_state
		if not ws:
			return
		ws_title = frappe.db.get_value("Workflow State", ws, "workflow_state_name") or ws
		if ws_title == "Rejected":
			self.status = "Cancelled"

	def _create_clearance_journal_entry(self):
		"""Single Journal Entry: expense/tax debits, PI payable debits with ERPNext invoice refs, one petty cash credit.

		PI settlement follows the cheque_management pattern: debit supplier payable with ``party_type`` /
		``party`` / ``reference_type`` = Purchase Invoice / ``reference_name`` = invoice id so outstanding is
		updated via standard JE allocation (no Payment Entry on clearance).
		"""
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

		expense_rows = [r for r in self.details if not r.purchase_invoice]
		groups = defaultdict(lambda: {"amount": 0.0, "tax": 0.0})

		for row in expense_rows:
			et = frappe.get_cached_doc("PM Expense Type", row.expense_type)
			exp_acc = et.expense_account
			cc = row.cost_center or et.default_cost_center
			prj = row.project or self.project
			tax_acc = et.tax_account if flt(row.tax_amount) else None
			use_split = bool(tax_acc and flt(row.tax_amount))
			key = (exp_acc, cc or "", prj or "", use_split, tax_acc or "")
			groups[key]["amount"] += flt(row.amount)
			groups[key]["tax"] += flt(row.tax_amount)

		for (exp_acc, cc, prj, use_split, tax_acc), sums in groups.items():
			base = sums["amount"]
			tax = sums["tax"]
			if use_split:
				je.append(
					"accounts",
					{
						"account": exp_acc,
						"debit_in_account_currency": base,
						"credit_in_account_currency": 0,
						"cost_center": cc or None,
						"project": prj or None,
					},
				)
				je.append(
					"accounts",
					{
						"account": tax_acc,
						"debit_in_account_currency": tax,
						"credit_in_account_currency": 0,
						"cost_center": cc or None,
						"project": prj or None,
					},
				)
				total_petty_credit += base + tax
			else:
				debit_total = base + tax
				je.append(
					"accounts",
					{
						"account": exp_acc,
						"debit_in_account_currency": debit_total,
						"credit_in_account_currency": 0,
						"cost_center": cc or None,
						"project": prj or None,
					},
				)
				total_petty_credit += debit_total

		for row in self.details:
			if not row.purchase_invoice:
				continue
			pi = frappe.get_doc("Purchase Invoice", row.purchase_invoice)
			alloc = flt(row.allocated_amount)
			je.append(
				"accounts",
				{
					"account": pi.credit_to,
					"party_type": "Supplier",
					"party": pi.supplier,
					"reference_type": "Purchase Invoice",
					"reference_name": pi.name,
					"debit_in_account_currency": alloc,
					"credit_in_account_currency": 0,
				},
			)
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
