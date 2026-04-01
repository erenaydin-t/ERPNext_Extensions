# Copyright (c) 2025, Farbod Siyahpoosh and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import getdate


def _get_party_account_or_company_default(party_type, party, company, account_kind="receivable"):
	"""Get party account; fallback to company default. account_kind: receivable or payable."""
	# ERPNext's party account helper is primarily designed for Customer/Supplier.
	# For Employee/Shareholder we intentionally fallback to company defaults.
	if party_type in ("Employee", "Shareholder"):
		if account_kind == "receivable":
			return frappe.get_cached_value("Company", company, "default_receivable_account")
		return frappe.get_cached_value("Company", company, "default_payable_account")
	try:
		from erpnext.accounts.party import get_party_account
		account = get_party_account(party_type, party, company)
		if account:
			return account
	except Exception:
		pass
	# Fallback: company default
	if account_kind == "receivable":
		return frappe.get_cached_value("Company", company, "default_receivable_account")
	return frappe.get_cached_value("Company", company, "default_payable_account")


@frappe.whitelist()
def get_default_party_accounts(party_type, party, company, cheque_direction):
	"""Return default Account Paid From / Account Paid To for the given party and direction."""
	if not all([party_type, party, company, cheque_direction]):
		return {}
	out = {}
	if cheque_direction == "Receivable":
		out["account_paid_from"] = _get_party_account_or_company_default(
			party_type, party, company, "receivable"
		)
	if cheque_direction == "Payable":
		out["account_paid_to"] = _get_party_account_or_company_default(
			party_type, party, company, "payable"
		)
	return out


class PostDatedCheque(Document):
	def before_insert(self):
		"""Set defaults for new PDC."""
		if not self.cheque_status:
			self.cheque_status = "Draft"
		if not self.workflow_state:
			self.workflow_state = "Draft"
		# Initial holder = party (Received From / Paid To)
		if not self.holder_party and self.party:
			self.holder_party_type = self.party_type
			self.holder_party = self.party

	def before_save(self):
		"""When workflow_state changes to Registered, create Register Cheque JE in the same save."""
		if self.docstatus != 1:
			return
		if self.workflow_state != "Registered":
			return
		old_state = None
		if getattr(self, "_doc_before_save", None):
			old_state = self._doc_before_save.get("workflow_state")
		elif self.name and frappe.db.exists("Post Dated Cheque", self.name):
			old_state = frappe.db.get_value("Post Dated Cheque", self.name, "workflow_state")
		if old_state == "Registered":
			return  # Already registered, avoid duplicate JE
		if self._has_register_entry():
			return
		self._create_register_cheque_je()

	def validate(self):
		"""Validate PDC data and enforce immutability after submit."""
		self._set_default_party_accounts()
		self._validate_party()
		self._validate_duplicate_cheque_no()
		self._validate_drawer_bank()
		self._validate_party_immutable_after_submit()

	def _validate_drawer_bank(self):
		"""Drawer bank is required for receivable cheques."""
		if self.cheque_direction == "Receivable" and not self.drawer_bank_name:
			frappe.throw(frappe._("Drawer Bank Name is required for Receivable cheques."))

	def _set_default_party_accounts(self):
		"""Set Account Paid From/To from party default or company default if empty."""
		if not self.company or not self.party_type or not self.party:
			return
		if self.cheque_direction == "Receivable" and not self.account_paid_from:
			self.account_paid_from = _get_party_account_or_company_default(
				self.party_type, self.party, self.company, "receivable"
			)
		if self.cheque_direction == "Payable" and not self.account_paid_to:
			self.account_paid_to = _get_party_account_or_company_default(
				self.party_type, self.party, self.company, "payable"
			)

	def _validate_party(self):
		if not self.party_type or not self.party:
			frappe.throw(
				frappe._("Party Type and Party are required for {0} cheque.").format(
					self.cheque_direction or ""
				)
			)
		# Optional: party_type vs direction guidance (non-blocking)
		receivable_party_types = {"Customer", "Employee", "Shareholder"}
		payable_party_types = {"Supplier", "Employee", "Shareholder"}

		if self.cheque_direction == "Receivable" and self.party_type not in receivable_party_types:
			frappe.msgprint(
				frappe._("Receivable cheques typically use Party Type: Customer."),
				indicator="orange",
				alert=True,
			)
		if self.cheque_direction == "Payable" and self.party_type not in payable_party_types:
			frappe.msgprint(
				frappe._("Payable cheques typically use Party Type: Supplier."),
				indicator="orange",
				alert=True,
			)

	def _validate_duplicate_cheque_no(self):
		if not self.cheque_no or not self.company:
			return
		filters = {
			"cheque_no": self.cheque_no,
			"company": self.company,
			"name": ["!=", self.name or ""],
		}
		if frappe.db.exists("Post Dated Cheque", filters):
			frappe.throw(
				frappe._("Cheque Number {0} already exists for company {1}.").format(
					self.cheque_no, self.company
				)
			)

	def _validate_party_immutable_after_submit(self):
		"""Party (Received From / Paid To) must not change after submit."""
		if self.docstatus != 1:
			return
		if not self.get("_doc_before_save"):
			return
		before = self._doc_before_save
		if (before.party_type != self.party_type) or (before.party != self.party):
			frappe.throw(
				frappe._(
					"Cannot change Party Type or Party after submit. Cancel the document to make changes."
				)
			)

	def get_pdc_settings(self):
		"""Get PDC Settings for the company (by name or by company field)."""
		if not self.company:
			frappe.throw(frappe._("Company is required"))
		name = frappe.db.get_value("PDC Settings", {"company": self.company}, "name")
		if not name:
			name = self.company
		if not name or not frappe.db.exists("PDC Settings", name):
			frappe.throw(
				frappe._("PDC Settings not found for company {0}. Please create PDC Settings first.").format(
					self.company
				)
			)
		return frappe.get_doc("PDC Settings", name)

	def _has_register_entry(self):
		"""Check if Register JE already exists (Receive for receivable, Payable Issue for payable)."""
		for ref in (self.journal_references or []):
			if ref.purpose in ("Receive", "Payable Issue"):
				return True
		if self.name:
			count = frappe.db.count(
				"PDC Journal Reference",
				{"parent": self.name, "parenttype": "Post Dated Cheque", "purpose": ["in", ["Receive", "Payable Issue"]]},
			)
			if count and count > 0:
				return True
		return False

	def _create_register_cheque_je(self, posting_date=None):
		"""
		Create Journal Entry when transitioning to Registered.
		Receivable: Dr Cheques in Hand, Cr Account Paid From (party receivable).
		Payable: Dr Account Paid To (party payable), Cr Cheques Payable.
		"""
		if self._has_register_entry():
			return None
		settings = self.get_pdc_settings()
		posting_date = posting_date or getdate()

		if self.cheque_direction == "Receivable":
			if not settings.get("default_cheques_in_hand_account"):
				frappe.throw(
					frappe._("Cheques in Hand Account is not set in PDC Settings for company {0}.").format(
						self.company
					)
				)
			if not self.account_paid_from:
				frappe.throw(
					frappe._("Account Paid From is required for Receivable cheque. Set it or select Party first.")
				)
			je = frappe.new_doc("Journal Entry")
			je.posting_date = posting_date
			je.company = self.company
			je.voucher_type = "Journal Entry"
			je.cheque_no = self.cheque_no
			je.cheque_date = self.cheque_due_date
			je.user_remark = frappe._("Cheque {0} received from party - PDC Register").format(self.cheque_no)
			je.append(
				"accounts",
				{
					"account": settings.default_cheques_in_hand_account,
					"debit_in_account_currency": self.cheque_amount,
					"party_type": self.party_type,
					"party": self.party,
				},
			)
			je.append(
				"accounts",
				{
					"account": self.account_paid_from,
					"credit_in_account_currency": self.cheque_amount,
					"party_type": self.party_type,
					"party": self.party,
				},
			)
			je.flags.ignore_permissions = True
			je.save()
			je.submit()
			self.append(
				"journal_references",
				{
					"journal_entry": je.name,
					"purpose": "Receive",
					"posting_date": posting_date,
					"amount": self.cheque_amount,
				},
			)
			self.cheque_status = "Received"
			return je

		if self.cheque_direction == "Payable":
			if not settings.get("default_payable_cheque_account"):
				frappe.throw(
					frappe._("Default Payable Cheque Account is not set in PDC Settings for company {0}.").format(
						self.company
					)
				)
			if not self.account_paid_to:
				frappe.throw(
					frappe._("Account Paid To is required for Payable cheque. Set it or select Party first.")
				)
			je = frappe.new_doc("Journal Entry")
			je.posting_date = posting_date
			je.company = self.company
			je.voucher_type = "Journal Entry"
			je.cheque_no = self.cheque_no
			je.cheque_date = self.cheque_due_date
			je.user_remark = frappe._("Cheque {0} issued to party - PDC Register").format(self.cheque_no)
			je.append(
				"accounts",
				{
					"account": self.account_paid_to,
					"debit_in_account_currency": self.cheque_amount,
					"party_type": self.party_type,
					"party": self.party,
				},
			)
			je.append(
				"accounts",
				{
					"account": settings.default_payable_cheque_account,
					"credit_in_account_currency": self.cheque_amount,
					"party_type": self.party_type,
					"party": self.party,
				},
			)
			je.flags.ignore_permissions = True
			je.save()
			je.submit()
			self.append(
				"journal_references",
				{
					"journal_entry": je.name,
					"purpose": "Payable Issue",
					"posting_date": posting_date,
					"amount": self.cheque_amount,
				},
			)
			self.cheque_status = "Issued"
			return je

		return None


def on_pdc_update_after_submit(doc, method=None):
	"""
	When workflow_state changes to Registered, create the Register Cheque Journal Entry
	(Receive for receivable, Payable Issue for payable) and update cheque_status.
	"""
	if doc.workflow_state != "Registered":
		return
	doc.reload()
	if doc._has_register_entry():
		return
	doc._create_register_cheque_je()
	doc.flags.ignore_validate_update_after_submit = True
	doc.save()
	frappe.msgprint(
		frappe._("Journal Entry created for Register Cheque."),
		indicator="green",
		alert=True,
	)
