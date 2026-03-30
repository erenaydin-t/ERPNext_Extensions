import frappe
from frappe.model.document import Document
from frappe.utils import getdate, flt

from erpnext.accounts.party import get_party_account

from erpnext_extensions.cheque_management.utils import (
	ReceivableChequeStatus,
	PayableChequeStatus,
	JournalEntryPurpose,
	ChequeType,
)


@frappe.whitelist()
def mark_waiting_for_sayad(name):
	"""Whitelisted method for Mark Waiting For Sayad"""
	doc = frappe.get_doc("Cheque", name)
	doc.mark_waiting_for_sayad()
	return doc


@frappe.whitelist()
def mark_registered_in_sayad(name):
	"""Whitelisted method for Mark Registered In Sayad"""
	doc = frappe.get_doc("Cheque", name)
	doc.mark_registered_in_sayad()
	return doc


@frappe.whitelist()
def move_to_box(name):
	"""Whitelisted method for Move To Box"""
	doc = frappe.get_doc("Cheque", name)
	doc.move_to_box()
	return doc


@frappe.whitelist()
def assign_to_bank(name, posting_date=None, bank_account=None):
	"""Whitelisted method for Assign To Bank"""
	doc = frappe.get_doc("Cheque", name)
	return doc.assign_to_bank(posting_date, bank_account)


@frappe.whitelist()
def mark_as_collected(name, posting_date=None, bank_account=None):
	"""Whitelisted method for Mark As Collected"""
	doc = frappe.get_doc("Cheque", name)
	return doc.mark_as_collected(posting_date, bank_account)


@frappe.whitelist()
def mark_as_returned_from_bank(name, posting_date=None):
	"""Whitelisted method for Mark As Returned From Bank"""
	doc = frappe.get_doc("Cheque", name)
	return doc.mark_as_returned_from_bank(posting_date)


@frappe.whitelist()
def return_to_customer(name):
	"""Whitelisted method for Return To Customer"""
	doc = frappe.get_doc("Cheque", name)
	doc.return_to_customer()
	return doc


@frappe.whitelist()
def reassign_to_bank(name, posting_date=None):
	"""Whitelisted method for Reassign To Bank"""
	doc = frappe.get_doc("Cheque", name)
	return doc.reassign_to_bank(posting_date)


@frappe.whitelist()
def return_not_registered_to_customer(name):
	"""Whitelisted method for Return Not Registered To Customer"""
	doc = frappe.get_doc("Cheque", name)
	doc.return_not_registered_to_customer()
	return doc


@frappe.whitelist()
def return_registered_to_customer(name):
	"""Whitelisted method for Return Registered To Customer"""
	doc = frappe.get_doc("Cheque", name)
	doc.return_registered_to_customer()
	return doc


@frappe.whitelist()
def retrieve_from_bank(name):
	"""Whitelisted method for Retrieve From Bank"""
	doc = frappe.get_doc("Cheque", name)
	doc.retrieve_from_bank()
	return doc


@frappe.whitelist()
def move_back_to_box_from_retrieved(name):
	"""Whitelisted method for Move Back To Box From Retrieved"""
	doc = frappe.get_doc("Cheque", name)
	doc.move_back_to_box_from_retrieved()
	return doc


# ========== Payable Cheque Whitelisted Methods ==========

@frappe.whitelist()
def select_bank(name):
	"""Whitelisted method for Select Bank"""
	doc = frappe.get_doc("Cheque", name)
	doc.select_bank()
	return doc


@frappe.whitelist()
def issue_cheque(name, posting_date=None):
	"""Whitelisted method for Issue Cheque"""
	doc = frappe.get_doc("Cheque", name)
	return doc.issue_cheque(posting_date)


@frappe.whitelist()
def mark_as_printed(name):
	"""Whitelisted method for Mark As Printed"""
	doc = frappe.get_doc("Cheque", name)
	doc.mark_as_printed()
	return doc


@frappe.whitelist()
def first_signature_done(name):
	"""Whitelisted method for First Signature Done"""
	doc = frappe.get_doc("Cheque", name)
	doc.first_signature_done()
	return doc


@frappe.whitelist()
def second_signature_done(name):
	"""Whitelisted method for Second Signature Done"""
	doc = frappe.get_doc("Cheque", name)
	doc.second_signature_done()
	return doc


@frappe.whitelist()
def notify_supplier(name):
	"""Whitelisted method for Notify Supplier"""
	doc = frappe.get_doc("Cheque", name)
	doc.notify_supplier()
	return doc


@frappe.whitelist()
def deliver_to_supplier(name):
	"""Whitelisted method for Deliver To Supplier"""
	doc = frappe.get_doc("Cheque", name)
	doc.deliver_to_supplier()
	return doc


@frappe.whitelist()
def mark_registered_in_sayad_payable(name):
	"""Whitelisted method for Mark Registered In Sayad (Payable)"""
	doc = frappe.get_doc("Cheque", name)
	doc.mark_registered_in_sayad_payable()
	return doc


@frappe.whitelist()
def mark_sayad_success(name):
	"""Whitelisted method for Mark Sayad Success"""
	doc = frappe.get_doc("Cheque", name)
	doc.mark_sayad_success()
	return doc


@frappe.whitelist()
def mark_as_void(name):
	"""Whitelisted method for Mark As Void"""
	doc = frappe.get_doc("Cheque", name)
	doc.mark_as_void()
	return doc


class Cheque(Document):
	def before_insert(self):
		"""Set default status to Draft for new cheques"""
		if not self.status:
			# New cheques start in Draft state
			self.status = "Draft"
	
	def before_save(self):
		"""Validate before save - check status changes and required fields"""
		# Get old status if available (from _doc_before_save or from database)
		old_status = None
		if self._doc_before_save and hasattr(self._doc_before_save, 'status'):
			old_status = self._doc_before_save.status
		elif self.name and frappe.db.exists("Cheque", self.name):
			# If document exists, get old status from database
			old_status = frappe.db.get_value("Cheque", self.name, "status")
		
		# Validate Sayad Code when status changes to Registered In Sayad
		if (self.cheque_type == ChequeType.RECEIVABLE and 
			self.status == ReceivableChequeStatus.REGISTERED_IN_SAYAD):
			# Only validate if status is actually changing (not just loading existing document)
			if old_status != ReceivableChequeStatus.REGISTERED_IN_SAYAD:
				if not self.sayad_code:
					# Revert status and workflow_state to previous values
					if old_status:
						self.status = old_status
						if frappe.db.exists("Workflow State", old_status):
							self.workflow_state = old_status
					frappe.throw("Sayad Code is required when transitioning to 'Registered In Sayad'. Please enter the Sayad registration code before proceeding.")
		
		# Validate Bank Account when status changes to Under Collection (Assign To Bank)
		if (self.cheque_type == ChequeType.RECEIVABLE and 
			self.status == ReceivableChequeStatus.UNDER_COLLECTION):
			# Only validate if status is actually changing
			if old_status != ReceivableChequeStatus.UNDER_COLLECTION:
				if not self.bank_account:
					# Revert status and workflow_state to previous values
					if old_status:
						self.status = old_status
						if frappe.db.exists("Workflow State", old_status):
							self.workflow_state = old_status
					frappe.throw("Bank Account is required when transitioning to 'Under Collection'. Please select a bank account before proceeding.")
				# Create Under Collection JE in same save (workflow only updates status; JE must be created here)
				self.assigned_to_bank_date = self.assigned_to_bank_date or getdate()
				if not self.has_under_collection_entry():
					self.create_under_collection_entry(self.assigned_to_bank_date, skip_save=True)
		
		# Validate Bank Account when status changes to Collected
		if (self.cheque_type == ChequeType.RECEIVABLE and 
			self.status == ReceivableChequeStatus.COLLECTED):
			# Only validate if status is actually changing
			if old_status != ReceivableChequeStatus.COLLECTED:
				if not self.bank_account:
					# Revert status and workflow_state to previous values
					if old_status:
						self.status = old_status
						if frappe.db.exists("Workflow State", old_status):
							self.workflow_state = old_status
					frappe.throw("Bank Account is required when transitioning to 'Collected'. Please select a bank account before proceeding.")
		
	def validate(self):
		"""Validate cheque data"""
		# Set default status to Draft if not set
		if not self.status:
			self.status = "Draft"
		
		# If status is Draft, allow it (this is the initial state)
		if self.status == "Draft":
			pass
		# Validate status based on cheque_type for non-draft states
		elif self.cheque_type == ChequeType.RECEIVABLE:
			# If status doesn't belong to Receivable workflow, reset to Draft
			if not ReceivableChequeStatus.is_valid(self.status) and self.status != "Draft":
				self.status = "Draft"
		elif self.cheque_type == ChequeType.PAYABLE:
			# If status doesn't belong to Payable workflow, reset to Draft
			if not PayableChequeStatus.is_valid(self.status) and self.status != "Draft":
				self.status = "Draft"
		
		# Sync workflow_state with status field for backward compatibility
		# workflow_state_field is set to "status" in workflow, so workflow_state should always match status
		# workflow_state is a Link field to "Workflow State" doctype, and the name of Workflow State records
		# matches the status values (e.g., "Draft", "Received From Customer", etc.)
		# This ensures UI consistency (both fields show the same value)
		if self.status:
			# Check if Workflow State record exists with this name
			if frappe.db.exists("Workflow State", self.status):
				self.workflow_state = self.status
			else:
				# If Workflow State doesn't exist, log a warning but don't break
				frappe.log_error(
					f"Workflow State '{self.status}' not found. workflow_state not synced.",
					"Cheque Workflow State Sync Warning"
				)
		
		# Set party_type based on cheque_type if not set
		if not self.party_type:
			if self.cheque_type == ChequeType.RECEIVABLE:
				self.party_type = "Customer"
			elif self.cheque_type == ChequeType.PAYABLE:
				self.party_type = "Supplier"
		
		# Validate duplicate cheque number in same company
		if self.cheque_no and self.company:
			duplicate = frappe.db.exists("Cheque", {
				"cheque_no": self.cheque_no,
				"company": self.company,
				"name": ["!=", self.name]
			})
			if duplicate:
				frappe.throw(f"Cheque Number {self.cheque_no} already exists for company {self.company}")
		
		# Validate party is required
		if not self.party:
			frappe.throw(f"Party is required for {self.cheque_type} cheque")
		
		# Validate bank account for Payable cheques when issuing
		if self.cheque_type == ChequeType.PAYABLE and self.status == PayableChequeStatus.SELECT_BANK:
			if not self.bank_account:
				frappe.throw("Bank Account is required for Payable cheques")
		
		# Note: Status change validations are now in before_save() hook
		# This ensures validation happens before the document is saved
		
		# Prevent Cheque User from manually changing status
		# Status should only be changed through action methods
		if self._doc_before_save and hasattr(self._doc_before_save, 'status'):
			if self.status != self._doc_before_save.status:
				# Allow if user has submit permission (Cheque Manager)
				if not frappe.has_permission("Cheque", "submit", self.name):
					frappe.throw("You do not have permission to change status. Please use action buttons.", frappe.PermissionError)
		
		# Prevent editing important fields after submit
		if self.docstatus == 1 and self._doc_before_save:
			# List of fields that cannot be changed after submit
			protected_fields = ['cheque_no', 'cheque_date', 'cheque_amount', 'party_type', 'party', 'company', 'cheque_type']
			for field in protected_fields:
				if hasattr(self._doc_before_save, field) and getattr(self, field) != getattr(self._doc_before_save, field):
					frappe.throw(
						f"Cannot change {field} after cheque is submitted. Please cancel the cheque first.",
						frappe.ValidationError
					)
		
		# Prevent editing cheque if it has Journal Entries (unless cancelling)
		# Only allow editing if document is in draft state and has no Journal Entries
		if self.docstatus == 0 and self.journal_references and len(self.journal_references) > 0:
			# Check if this is a real change (not just loading the document)
			if self._doc_before_save:
				# Allow if user is cancelling Journal Entries or has special permission
				if not frappe.has_permission("Cheque", "cancel", self.name):
					frappe.throw(
						"Cannot edit cheque that has Journal Entries. Please cancel the Journal Entries first or contact Cheque Manager.",
						frappe.ValidationError
					)
	
	def before_submit(self):
		"""Set received_date and create Receive JE *before* submit. If JE fails, abort submit (status stays as before)."""
		if self.cheque_type != ChequeType.RECEIVABLE or self.has_receive_entry():
			return
		# Set received_date only if user left it blank (cannot change after submit)
		if not self.received_date:
			self.received_date = getdate()
		posting_date = self.received_date or getdate()
		je = self.create_receive_entry(posting_date)
		if not je:
			frappe.throw(
				"Could not create Receive Journal Entry. Submit aborted; cheque status unchanged.",
				frappe.ValidationError
			)
		frappe.msgprint(
			f"Journal Entry <a href='/app/journal-entry/{je.name}'>{je.name}</a> created for receiving cheque.",
			indicator="green"
		)
	
	def on_submit(self):
		"""Status change from Draft handled in before_submit (Receive JE) or workflow."""
		# Change status from Draft to Received From Customer on submit (when not using workflow)
		if self.status == "Draft":
			if self.cheque_type == ChequeType.RECEIVABLE:
				self.status = ReceivableChequeStatus.RECEIVED_FROM_CUSTOMER
			elif self.cheque_type == ChequeType.PAYABLE:
				self.status = PayableChequeStatus.PAYMENT_REQUEST_CREATED
	
	def get_cheque_settings(self):
		"""Get Cheque Settings for the company"""
		# Try to get by company filter first
		settings_name = frappe.db.get_value(
			"Cheque Settings",
			{"company": self.company},
			"name"
		)
		
		if settings_name:
			return frappe.get_doc("Cheque Settings", settings_name)
		
		# If not found, try to get single (if it's truly single)
		try:
			settings = frappe.get_single("Cheque Settings")
			if settings.company == self.company:
				return settings
		except frappe.DoesNotExistError:
			pass
		
		frappe.throw(f"Cheque Settings not found for company {self.company}. Please create Cheque Settings first.")
	
	def has_receive_entry(self):
		"""Check if Receive Journal Entry already exists for this cheque"""
		for ref in self.journal_references:
			if ref.purpose == JournalEntryPurpose.RECEIVE:
				return True
		return False

	def has_under_collection_entry(self):
		"""Check if Under Collection Journal Entry already exists for this cheque"""
		for ref in self.journal_references:
			if ref.purpose == JournalEntryPurpose.UNDER_COLLECTION:
				return True
		return False
	
	def create_receive_entry(self, posting_date=None):
		"""
		Create Journal Entry for receiving cheque from customer
		For Receivable cheques only
		Debit: Receivable Cheque Account
		Credit: Customer Account (Accounts Receivable)
		"""
		if self.cheque_type != ChequeType.RECEIVABLE:
			frappe.throw("Receive entry is only for Receivable cheques")
		
		# Don't create if already exists
		if self.has_receive_entry():
			return None
		
		settings = self.get_cheque_settings()
		
		if not settings.default_receivable_cheque_account:
			frappe.throw("Default Receivable Cheque Account is not set in Cheque Settings")
		
		# Get customer account using ERPNext utility function
		# This will create Party Account if it doesn't exist
		try:
			party_account = get_party_account(
				self.party_type,
				self.party,
				self.company
			)
		except Exception as e:
			frappe.throw(f"Could not get Party Account for {self.party_type} {self.party} in company {self.company}: {str(e)}")
		
		posting_date = posting_date or getdate()
		
		je = frappe.new_doc("Journal Entry")
		je.posting_date = posting_date
		je.company = self.company
		je.voucher_type = "Journal Entry"
		je.cheque_no = self.cheque_no
		je.user_remark = f"Cheque {self.cheque_no} received from customer"
		if self.cheque_date:
			je.cheque_date = self.cheque_date
		
		# Debit: Receivable Cheque Account
		je.append("accounts", {
			"account": settings.default_receivable_cheque_account,
			"debit_in_account_currency": self.cheque_amount,
			"party_type": self.party_type,
			"party": self.party,
		})
		
		# Credit: Customer Account (Accounts Receivable)
		je.append("accounts", {
			"account": party_account,
			"credit_in_account_currency": self.cheque_amount,
			"party_type": self.party_type,
			"party": self.party,
		})
		
		je.save()
		je.submit()
		
		# Add to journal references if document exists (not during initial insert)
		# During insert, workflow hook will handle adding the reference
		if self.name and frappe.db.exists("Cheque", self.name):
			self.append("journal_references", {
				"journal_entry": je.name,
				"purpose": JournalEntryPurpose.RECEIVE,
				"posting_date": posting_date,
				"amount": self.cheque_amount,
			})
			# Don't submit here - let the workflow hook handle it
			# This allows the cheque to remain editable until moving to next state
		
		return je
	
	def create_under_collection_entry(self, posting_date=None, skip_save=False):
		"""
		Create Journal Entry for moving cheque to Under Collection
		For Receivable cheques only.
		When skip_save=True (e.g. from before_save), only create JE and append to doc; do not save/submit doc.
		"""
		if self.cheque_type != ChequeType.RECEIVABLE:
			frappe.throw("Under Collection entry is only for Receivable cheques")
		if skip_save and self.has_under_collection_entry():
			return None

		settings = self.get_cheque_settings()

		if not settings.default_receivable_cheque_account:
			frappe.throw("Default Receivable Cheque Account is not set in Cheque Settings")
		if not settings.default_under_collection_account:
			frappe.throw("Default Under Collection Account is not set in Cheque Settings")

		posting_date = posting_date or getdate()

		je = frappe.new_doc("Journal Entry")
		je.posting_date = posting_date
		je.company = self.company
		je.voucher_type = "Journal Entry"
		je.cheque_no = self.cheque_no
		je.user_remark = f"Cheque {self.cheque_no} moved to Under Collection"
		je.cheque_date = self.cheque_date

		# Debit: Under Collection Account
		je.append("accounts", {
			"account": settings.default_under_collection_account,
			"debit_in_account_currency": self.cheque_amount,
			"party_type": self.party_type,
			"party": self.party,
		})

		# Credit: Receivable Cheque Account
		je.append("accounts", {
			"account": settings.default_receivable_cheque_account,
			"credit_in_account_currency": self.cheque_amount,
			"party_type": self.party_type,
			"party": self.party,
		})

		je.save()
		je.submit()

		# Add to journal references
		self.append("journal_references", {
			"journal_entry": je.name,
			"purpose": JournalEntryPurpose.UNDER_COLLECTION,
			"posting_date": posting_date,
			"amount": self.cheque_amount,
		})

		if skip_save:
			return je

		self.status = ReceivableChequeStatus.UNDER_COLLECTION
		self.save()
		if self.docstatus == 0:
			self.submit()

		return je
	
	def create_collection_entry(self, posting_date=None, bank_account=None):
		"""
		Create Journal Entry for collecting the cheque
		For Receivable cheques only
		"""
		if self.cheque_type != ChequeType.RECEIVABLE:
			frappe.throw("Collection entry is only for Receivable cheques")
		
		settings = self.get_cheque_settings()
		
		if not settings.default_under_collection_account:
			frappe.throw("Default Under Collection Account is not set in Cheque Settings")
		
		bank_account = bank_account or settings.default_bank_account
		if not bank_account:
			frappe.throw("Bank Account is required. Set it in Cheque Settings or pass as parameter")
		
		posting_date = posting_date or getdate()
		
		je = frappe.new_doc("Journal Entry")
		je.posting_date = posting_date
		je.company = self.company
		je.voucher_type = "Journal Entry"
		je.cheque_no = self.cheque_no
		je.user_remark = f"Cheque {self.cheque_no} collected"
		je.cheque_date=self.cheque_date
		# Debit: Bank Account
		je.append("accounts", {
			"account": bank_account,
			"debit_in_account_currency": self.cheque_amount,
		})
		
		# Credit: Under Collection Account
		je.append("accounts", {
			"account": settings.default_under_collection_account,
			"credit_in_account_currency": self.cheque_amount,
			"party_type": self.party_type,
			"party": self.party,
		})
		
		je.save()
		je.submit()
		
		# Add to journal references
		self.append("journal_references", {
			"journal_entry": je.name,
			"purpose": JournalEntryPurpose.COLLECTED,
			"posting_date": posting_date,
			"amount": self.cheque_amount,
		})
		
		self.status = ReceivableChequeStatus.COLLECTED
		self.save()
		# Submit cheque after creating Journal Entry to prevent further editing
		if self.docstatus == 0:
			self.submit()
		
		return je
	
	def create_return_entry(self, posting_date=None):
		"""
		Create Journal Entry for returning the cheque
		For Receivable cheques only
		"""
		if self.cheque_type != ChequeType.RECEIVABLE:
			frappe.throw("Return entry is only for Receivable cheques")
		
		settings = self.get_cheque_settings()
		
		if not settings.default_returned_cheque_account:
			frappe.throw("Default Returned Cheque Account is not set in Cheque Settings")
		
		# Determine source account based on current status
		source_account = None
		if self.status == ReceivableChequeStatus.UNDER_COLLECTION:
			if not settings.default_under_collection_account:
				frappe.throw("Default Under Collection Account is not set in Cheque Settings")
			source_account = settings.default_under_collection_account
		elif self.status == ReceivableChequeStatus.RECEIVED_FROM_CUSTOMER:
			if not settings.default_receivable_cheque_account:
				frappe.throw("Default Receivable Cheque Account is not set in Cheque Settings")
			source_account = settings.default_receivable_cheque_account
		else:
			frappe.throw(f"Cannot return cheque from status: {self.status}")
		
		posting_date = posting_date or getdate()
		
		je = frappe.new_doc("Journal Entry")
		je.posting_date = posting_date
		je.company = self.company
		je.voucher_type = "Journal Entry"
		je.cheque_no = self.cheque_no
		je.user_remark = f"Cheque {self.cheque_no} returned"
		je.cheque_date=self.cheque_date
		
		# Debit: Returned Cheque Account
		je.append("accounts", {
			"account": settings.default_returned_cheque_account,
			"debit_in_account_currency": self.cheque_amount,
			"party_type": self.party_type,
			"party": self.party,
		})
		
		# Credit: Source Account (Under Collection or Receivable)
		je.append("accounts", {
			"account": source_account,
			"credit_in_account_currency": self.cheque_amount,
			"party_type": self.party_type,
			"party": self.party,
		})
		
		je.save()
		je.submit()
		
		# Add to journal references
		self.append("journal_references", {
			"journal_entry": je.name,
			"purpose": JournalEntryPurpose.RETURNED,
			"posting_date": posting_date,
			"amount": self.cheque_amount,
		})
		
		self.status = ReceivableChequeStatus.RETURNED
		self.save()
		# Submit cheque after creating Journal Entry to prevent further editing
		if self.docstatus == 0:
			self.submit()
		
		return je
	
	def create_payable_issue_entry(self, posting_date=None, bank_account=None):
		"""
		Create Journal Entry for issuing payable cheque
		For Payable cheques only
		"""
		if self.cheque_type != ChequeType.PAYABLE:
			frappe.throw("Payable Issue entry is only for Payable cheques")
		
		settings = self.get_cheque_settings()
		
		if not settings.default_payable_cheque_account:
			frappe.throw("Default Payable Cheque Account is not set in Cheque Settings")
		
		bank_account = bank_account or settings.default_bank_account
		if not bank_account:
			frappe.throw("Bank Account is required. Set it in Cheque Settings or pass as parameter")
		
		posting_date = posting_date or getdate()
		
		je = frappe.new_doc("Journal Entry")
		je.posting_date = posting_date
		je.company = self.company
		je.voucher_type = "Journal Entry"
		je.cheque_no = self.cheque_no
		je.user_remark = f"Payable Cheque {self.cheque_no} issued"
		je.cheque_date=self.cheque_date
		# Debit: Payable Cheque Account
		je.append("accounts", {
			"account": settings.default_payable_cheque_account,
			"debit_in_account_currency": self.cheque_amount,
			"party_type": self.party_type,
			"party": self.party,
		})
		
		# Credit: Bank Account
		je.append("accounts", {
			"account": bank_account,
			"credit_in_account_currency": self.cheque_amount,
		})
		
		je.save()
		je.submit()
		
		# Add to journal references
		self.append("journal_references", {
			"journal_entry": je.name,
			"purpose": JournalEntryPurpose.PAYABLE_ISSUE,
			"posting_date": posting_date,
			"amount": self.cheque_amount,
		})
		
		self.status = PayableChequeStatus.ISSUED
		self.save()
		# Submit cheque after creating Journal Entry to prevent further editing
		if self.docstatus == 0:
			self.submit()
		
		return je
	
	def create_payable_clear_entry(self, posting_date=None):
		"""
		Create Journal Entry for clearing payable cheque
		For Payable cheques only
		"""
		if self.cheque_type != ChequeType.PAYABLE:
			frappe.throw("Payable Clear entry is only for Payable cheques")
		
		settings = self.get_cheque_settings()
		
		if not settings.default_payable_cheque_account:
			frappe.throw("Default Payable Cheque Account is not set in Cheque Settings")
		
		posting_date = posting_date or getdate()
		
		je = frappe.new_doc("Journal Entry")
		je.posting_date = posting_date
		je.company = self.company
		je.voucher_type = "Journal Entry"
		je.cheque_no = self.cheque_no
		je.user_remark = f"Payable Cheque {self.cheque_no} cleared"
		je.cheque_date=self.cheque_date
		# Debit: Party Account (Supplier) using ERPNext utility function
		# This will create Party Account if it doesn't exist
		try:
			party_account = get_party_account(
				self.party_type,
				self.party,
				self.company
			)
		except Exception as e:
			frappe.throw(f"Could not get Party Account for {self.party_type} {self.party} in company {self.company}: {str(e)}")
		
		je.append("accounts", {
			"account": party_account,
			"debit_in_account_currency": self.cheque_amount,
			"party_type": self.party_type,
			"party": self.party,
		})
		
		# Credit: Payable Cheque Account
		je.append("accounts", {
			"account": settings.default_payable_cheque_account,
			"credit_in_account_currency": self.cheque_amount,
			"party_type": self.party_type,
			"party": self.party,
		})
		
		je.save()
		je.submit()
		
		# Add to journal references
		self.append("journal_references", {
			"journal_entry": je.name,
			"purpose": JournalEntryPurpose.PAYABLE_CLEAR,
			"posting_date": posting_date,
			"amount": self.cheque_amount,
		})
		
		self.status = PayableChequeStatus.CLEARED
		self.save()
		# Submit cheque after creating Journal Entry to prevent further editing
		if self.docstatus == 0:
			self.submit()
		
		return je
	
	# ========== Receivable Cheque Action Methods ==========
	
	def mark_waiting_for_sayad(self):
		"""Mark cheque as Waiting For Sayad"""
		if self.cheque_type != ChequeType.RECEIVABLE:
			frappe.throw("This action is only for Receivable cheques")
		
		allowed_statuses = [
			ReceivableChequeStatus.RECEIVED_FROM_CUSTOMER,
		]
		
		if self.status not in allowed_statuses:
			frappe.throw(f"Cannot mark as Waiting For Sayad from status: {self.status}")
		
		self.status = ReceivableChequeStatus.WAITING_FOR_SAYAD
		self.save()
		frappe.msgprint(f"Cheque {self.cheque_no} marked as Waiting For Sayad")
	
	def mark_registered_in_sayad(self):
		"""Mark cheque as Registered In Sayad"""
		if self.cheque_type != ChequeType.RECEIVABLE:
			frappe.throw("This action is only for Receivable cheques")
		
		allowed_statuses = [
			ReceivableChequeStatus.WAITING_FOR_SAYAD,
		]
		
		if self.status not in allowed_statuses:
			frappe.throw(f"Cannot mark as Registered In Sayad from status: {self.status}")
		
		# Sayad Code is required when registering in Sayad
		if not self.sayad_code:
			frappe.throw("Sayad Code is required. Please enter the Sayad registration code before marking as Registered In Sayad.")
		
		self.status = ReceivableChequeStatus.REGISTERED_IN_SAYAD
		self.save()
		frappe.msgprint(f"Cheque {self.cheque_no} marked as Registered In Sayad")
	
	def move_to_box(self):
		"""Move cheque to Box"""
		if self.cheque_type != ChequeType.RECEIVABLE:
			frappe.throw("This action is only for Receivable cheques")
		
		allowed_statuses = [
			ReceivableChequeStatus.REGISTERED_IN_SAYAD,
		]
		
		if self.status not in allowed_statuses:
			frappe.throw(f"Cannot move to Box from status: {self.status}")
		
		self.status = ReceivableChequeStatus.MOVE_TO_BOX
		self.save()
		frappe.msgprint(f"Cheque {self.cheque_no} moved to Box")
	
	def assign_to_bank(self, posting_date=None, bank_account=None):
		"""Assign cheque to bank (creates Under Collection Journal Entry)"""
		if self.cheque_type != ChequeType.RECEIVABLE:
			frappe.throw("This action is only for Receivable cheques")
		
		allowed_statuses = [
			ReceivableChequeStatus.RECEIVED_FROM_CUSTOMER,
			ReceivableChequeStatus.MOVE_TO_BOX,
		]
		
		if self.status not in allowed_statuses:
			frappe.throw(f"Cannot assign to bank from status: {self.status}")
		
		# Bank account is required for assigning to bank
		bank_account = bank_account or self.bank_account
		if not bank_account:
			frappe.throw("Bank Account is required. Please select a bank account before assigning cheque to bank.")
		
		# Store bank account for reference
		self.bank_account = bank_account
		
		posting_date = posting_date or getdate()
		# Set assigned to bank date
		self.assigned_to_bank_date = posting_date
		
		je = self.create_under_collection_entry(posting_date)
		frappe.msgprint({
			"message": f"Cheque {self.cheque_no} assigned to bank. Journal Entry <a href='/app/journal-entry/{je.name}'>{je.name}</a> created.",
			"indicator": "green"
		})
		return {"name": je.name, "message": je}
	
	def mark_as_collected(self, posting_date=None, bank_account=None):
		"""Mark cheque as collected (creates Collection Journal Entry)"""
		if self.cheque_type != ChequeType.RECEIVABLE:
			frappe.throw("This action is only for Receivable cheques")
		
		# Check permission - only Cheque Manager can mark as collected
		if not frappe.has_permission("Cheque", "submit", self.name):
			frappe.throw("Only Cheque Manager can mark cheques as collected", frappe.PermissionError)
		
		allowed_statuses = [
			ReceivableChequeStatus.UNDER_COLLECTION,
		]
		
		if self.status not in allowed_statuses:
			frappe.throw(f"Cannot mark as collected from status: {self.status}")
		
		# Bank account is required for collection (to add to bank balance)
		bank_account = bank_account or self.bank_account
		if not bank_account:
			frappe.throw("Bank Account is required. Please select a bank account before marking cheque as collected.")
		
		posting_date = posting_date or getdate()
		# Set collected date
		self.collected_date = posting_date
		
		je = self.create_collection_entry(posting_date, bank_account)
		frappe.msgprint({
			"message": f"Cheque {self.cheque_no} marked as collected. Journal Entry <a href='/app/journal-entry/{je.name}'>{je.name}</a> created.",
			"indicator": "green"
		})
		return {"name": je.name, "message": je}
	
	def mark_as_returned_from_bank(self, posting_date=None):
		"""Mark cheque as returned from bank (creates Return Journal Entry)"""
		if self.cheque_type != ChequeType.RECEIVABLE:
			frappe.throw("This action is only for Receivable cheques")
		
		allowed_statuses = [
			ReceivableChequeStatus.UNDER_COLLECTION,
		]
		
		if self.status not in allowed_statuses:
			frappe.throw(f"Cannot mark as returned from bank from status: {self.status}")
		
		posting_date = posting_date or getdate()
		# Set returned from bank date
		self.returned_from_bank_date = posting_date
		
		je = self.create_return_entry(posting_date)
		self.status = ReceivableChequeStatus.RETURNED_FROM_BANK
		self.save()
		frappe.msgprint({
			"message": f"Cheque {self.cheque_no} marked as returned from bank. Journal Entry <a href='/app/journal-entry/{je.name}'>{je.name}</a> created.",
			"indicator": "orange"
		})
		return {"name": je.name, "message": je}
	
	def return_to_customer(self):
		"""Return cheque to customer"""
		if self.cheque_type != ChequeType.RECEIVABLE:
			frappe.throw("This action is only for Receivable cheques")
		
		allowed_statuses = [
			ReceivableChequeStatus.RETURNED_FROM_BANK,
			ReceivableChequeStatus.RETURNED,
		]
		
		if self.status not in allowed_statuses:
			frappe.throw(f"Cannot return to customer from status: {self.status}")
		
		# Set returned to customer date
		self.returned_to_customer_date = getdate()
		
		self.status = ReceivableChequeStatus.RETURN_TO_CUSTOMER
		self.save()
		frappe.msgprint(f"Cheque {self.cheque_no} returned to customer")
	
	def reassign_to_bank(self, posting_date=None):
		"""Reassign cheque to bank (creates Under Collection Journal Entry)"""
		if self.cheque_type != ChequeType.RECEIVABLE:
			frappe.throw("This action is only for Receivable cheques")
		
		allowed_statuses = [
			ReceivableChequeStatus.RETURNED_FROM_BANK,
			ReceivableChequeStatus.RETURNED,
			ReceivableChequeStatus.RETRIEVED_FROM_BANK,
		]
		
		if self.status not in allowed_statuses:
			frappe.throw(f"Cannot reassign to bank from status: {self.status}")
		
		je = self.create_under_collection_entry(posting_date)
		frappe.msgprint({
			"message": f"Cheque {self.cheque_no} reassigned to bank. Journal Entry <a href='/app/journal-entry/{je.name}'>{je.name}</a> created.",
			"indicator": "green"
		})
		return {"name": je.name, "message": je}
	
	def return_not_registered_to_customer(self):
		"""Return cheque to customer when customer doesn't register in Sayad"""
		if self.cheque_type != ChequeType.RECEIVABLE:
			frappe.throw("This action is only for Receivable cheques")
		
		allowed_statuses = [
			ReceivableChequeStatus.WAITING_FOR_SAYAD,
		]
		
		if self.status not in allowed_statuses:
			frappe.throw(f"Cannot return not registered cheque from status: {self.status}")
		
		self.status = ReceivableChequeStatus.RETURNED_NOT_REGISTERED
		self.save()
		frappe.msgprint(f"Cheque {self.cheque_no} returned to customer (not registered in Sayad)")
	
	def return_registered_to_customer(self):
		"""Return registered cheque to customer (cancellation/return request)"""
		if self.cheque_type != ChequeType.RECEIVABLE:
			frappe.throw("This action is only for Receivable cheques")
		
		allowed_statuses = [
			ReceivableChequeStatus.REGISTERED_IN_SAYAD,
		]
		
		if self.status not in allowed_statuses:
			frappe.throw(f"Cannot return registered cheque from status: {self.status}")
		
		self.status = ReceivableChequeStatus.RETURNED_REGISTERED_TO_CUSTOMER
		self.save()
		frappe.msgprint(f"Cheque {self.cheque_no} returned to customer (registered in Sayad)")
	
	def retrieve_from_bank(self):
		"""Retrieve cheque from bank without action (no collection, no return)"""
		if self.cheque_type != ChequeType.RECEIVABLE:
			frappe.throw("This action is only for Receivable cheques")
		
		allowed_statuses = [
			ReceivableChequeStatus.UNDER_COLLECTION,
		]
		
		if self.status not in allowed_statuses:
			frappe.throw(f"Cannot retrieve from bank from status: {self.status}")
		
		# Reverse the Under Collection Journal Entry
		# Find the most recent Under Collection JE
		under_collection_je = None
		for ref in self.journal_references:
			if ref.purpose == JournalEntryPurpose.UNDER_COLLECTION:
				under_collection_je = ref.journal_entry
				break
		
		if under_collection_je:
			# Cancel the JE if not already cancelled
			je_doc = frappe.get_doc("Journal Entry", under_collection_je)
			if je_doc.docstatus == 1:
				je_doc.cancel()
				frappe.msgprint(f"Under Collection Journal Entry {under_collection_je} cancelled")
		
		self.status = ReceivableChequeStatus.RETRIEVED_FROM_BANK
		self.save()
		frappe.msgprint(f"Cheque {self.cheque_no} retrieved from bank")
	
	def move_back_to_box_from_retrieved(self):
		"""Move cheque back to box after retrieving from bank"""
		if self.cheque_type != ChequeType.RECEIVABLE:
			frappe.throw("This action is only for Receivable cheques")
		
		allowed_statuses = [
			ReceivableChequeStatus.RETRIEVED_FROM_BANK,
		]
		
		if self.status not in allowed_statuses:
			frappe.throw(f"Cannot move to box from status: {self.status}")
		
		self.status = ReceivableChequeStatus.MOVE_TO_BOX
		self.save()
		frappe.msgprint(f"Cheque {self.cheque_no} moved back to Box")
	
	# ========== Payable Cheque Action Methods ==========
	
	def select_bank(self):
		"""Select bank for payable cheque"""
		if self.cheque_type != ChequeType.PAYABLE:
			frappe.throw("This action is only for Payable cheques")
		
		allowed_statuses = [
			PayableChequeStatus.PAYMENT_REQUEST_CREATED,
		]
		
		if self.status not in allowed_statuses:
			frappe.throw(f"Cannot select bank from status: {self.status}")
		
		if not self.bank_account:
			frappe.throw("Bank Account is required. Please select a bank account first.")
		
		self.status = PayableChequeStatus.SELECT_BANK
		self.save()
		frappe.msgprint(f"Bank {self.bank_account} selected for cheque {self.cheque_no}")
	
	def issue_cheque(self, posting_date=None):
		"""Issue payable cheque (creates Payable Issue Journal Entry)"""
		if self.cheque_type != ChequeType.PAYABLE:
			frappe.throw("This action is only for Payable cheques")
		
		allowed_statuses = [
			PayableChequeStatus.SELECT_BANK,
		]
		
		if self.status not in allowed_statuses:
			frappe.throw(f"Cannot issue cheque from status: {self.status}")
		
		if not self.bank_account:
			frappe.throw("Bank Account is required")
		
		je = self.create_payable_issue_entry(posting_date, self.bank_account)
		frappe.msgprint({
			"message": f"Cheque {self.cheque_no} issued. Journal Entry <a href='/app/journal-entry/{je.name}'>{je.name}</a> created.",
			"indicator": "green"
		})
		return {"name": je.name, "message": je}
	
	def mark_as_printed(self):
		"""Mark cheque as printed"""
		if self.cheque_type != ChequeType.PAYABLE:
			frappe.throw("This action is only for Payable cheques")
		
		allowed_statuses = [
			PayableChequeStatus.ISSUED,
		]
		
		if self.status not in allowed_statuses:
			frappe.throw(f"Cannot mark as printed from status: {self.status}")
		
		self.status = PayableChequeStatus.MARKED_AS_PRINTED
		self.save()
		frappe.msgprint(f"Cheque {self.cheque_no} marked as printed")
	
	def first_signature_done(self):
		"""Mark first signature as done"""
		if self.cheque_type != ChequeType.PAYABLE:
			frappe.throw("This action is only for Payable cheques")
		
		allowed_statuses = [
			PayableChequeStatus.MARKED_AS_PRINTED,
		]
		
		if self.status not in allowed_statuses:
			frappe.throw(f"Cannot mark first signature from status: {self.status}")
		
		self.status = PayableChequeStatus.FIRST_SIGNATURE_DONE
		self.save()
		frappe.msgprint(f"First signature done for cheque {self.cheque_no}")
	
	def second_signature_done(self):
		"""Mark second signature as done"""
		if self.cheque_type != ChequeType.PAYABLE:
			frappe.throw("This action is only for Payable cheques")
		
		allowed_statuses = [
			PayableChequeStatus.FIRST_SIGNATURE_DONE,
		]
		
		if self.status not in allowed_statuses:
			frappe.throw(f"Cannot mark second signature from status: {self.status}")
		
		self.status = PayableChequeStatus.SECOND_SIGNATURE_DONE
		self.save()
		frappe.msgprint(f"Second signature done for cheque {self.cheque_no}")
	
	def notify_supplier(self):
		"""Notify supplier about cheque"""
		if self.cheque_type != ChequeType.PAYABLE:
			frappe.throw("This action is only for Payable cheques")
		
		allowed_statuses = [
			PayableChequeStatus.SECOND_SIGNATURE_DONE,
		]
		
		if self.status not in allowed_statuses:
			frappe.throw(f"Cannot notify supplier from status: {self.status}")
		
		if not self.party:
			frappe.throw("Supplier is required")
		
		self.status = PayableChequeStatus.NOTIFY_SUPPLIER
		self.save()
		frappe.msgprint(f"Supplier {self.party} notified about cheque {self.cheque_no}")
	
	def deliver_to_supplier(self):
		"""Mark cheque as delivered to supplier"""
		if self.cheque_type != ChequeType.PAYABLE:
			frappe.throw("This action is only for Payable cheques")
		
		allowed_statuses = [
			PayableChequeStatus.NOTIFY_SUPPLIER,
		]
		
		if self.status not in allowed_statuses:
			frappe.throw(f"Cannot deliver to supplier from status: {self.status}")
		
		self.status = PayableChequeStatus.DELIVER_TO_SUPPLIER
		self.save()
		frappe.msgprint(f"Cheque {self.cheque_no} delivered to supplier")
	
	def mark_registered_in_sayad_payable(self):
		"""Mark payable cheque as registered in Sayad"""
		if self.cheque_type != ChequeType.PAYABLE:
			frappe.throw("This action is only for Payable cheques")
		
		allowed_statuses = [
			PayableChequeStatus.DELIVER_TO_SUPPLIER,
		]
		
		if self.status not in allowed_statuses:
			frappe.throw(f"Cannot mark as registered in Sayad from status: {self.status}")
		
		self.status = PayableChequeStatus.REGISTERED_IN_SAYAD
		self.save()
		frappe.msgprint(f"Cheque {self.cheque_no} marked as registered in Sayad")
	
	def mark_sayad_success(self):
		"""Mark Sayad registration as successful"""
		if self.cheque_type != ChequeType.PAYABLE:
			frappe.throw("This action is only for Payable cheques")
		
		allowed_statuses = [
			PayableChequeStatus.REGISTERED_IN_SAYAD,
		]
		
		if self.status not in allowed_statuses:
			frappe.throw(f"Cannot mark Sayad success from status: {self.status}")
		
		self.status = PayableChequeStatus.SAYAD_SUCCESS
		self.save()
		frappe.msgprint(f"Sayad registration successful for cheque {self.cheque_no}")
	
	def mark_as_void(self):
		"""Mark cheque as void (before clearing)"""
		if self.cheque_type != ChequeType.PAYABLE:
			frappe.throw("This action is only for Payable cheques")
		
		# Check permission - only Cheque Manager can void cheques
		if not frappe.has_permission("Cheque", "cancel", self.name):
			frappe.throw("Only Cheque Manager can void cheques", frappe.PermissionError)
		
		# Cannot void if already cleared
		if self.status == PayableChequeStatus.CLEARED:
			frappe.throw("Cannot void a cleared cheque")
		
		# Cannot void if already cancelled
		if self.status == PayableChequeStatus.CANCELLED:
			frappe.throw("Cheque is already cancelled")
		
		self.status = PayableChequeStatus.VOID
		self.save()
		frappe.msgprint(f"Cheque {self.cheque_no} marked as void")


def on_cheque_update(doc, method=None):
	"""
	Hook called when Cheque document is updated
	Handles workflow state changes and creates Journal Entries automatically
	Note: workflow_state_field is "status", so workflow changes status directly
	"""
	# Only process if status has changed (workflow changes status, not workflow_state)
	if not hasattr(doc, '_doc_before_save') or not doc._doc_before_save:
		return
	
	old_status = doc._doc_before_save.get('status') if doc._doc_before_save else None
	new_status = doc.get('status')
	
	# If status changed, sync workflow_state and create Journal Entry if needed
	if old_status != new_status and new_status:
		# Ensure workflow_state matches status (workflow_state_field = "status")
		# workflow_state is a Link field to "Workflow State" doctype
		if frappe.db.exists("Workflow State", new_status):
			doc.workflow_state = new_status
		
		# Create Journal Entry based on status change
		create_je_for_status_change(doc, old_status, new_status)


def create_je_for_status_change(doc, old_status, new_status):
	"""
	Create Journal Entry automatically when status changes to specific states
	Note: workflow_state_field is "status", so we check status changes
	"""
	try:
		# Receivable Cheque Journal Entry creation
		if doc.cheque_type == ChequeType.RECEIVABLE:
			if new_status == ReceivableChequeStatus.UNDER_COLLECTION and old_status != ReceivableChequeStatus.UNDER_COLLECTION:
				# Under Collection JE is created in before_save when workflow updates status.
				# If we reach here without one (e.g. transition via assign_to_bank()), create it and persist.
				if doc.has_under_collection_entry():
					return
				if not doc.bank_account:
					frappe.throw("Bank Account is required. Please select a bank account before assigning cheque to bank.")
				doc.assigned_to_bank_date = doc.assigned_to_bank_date or getdate()
				posting_date = doc.assigned_to_bank_date
				if not doc.has_receive_entry():
					frappe.log_error(
						"Receive Journal Entry not found when moving to Under Collection. Creating it now.",
						"Cheque Workflow Warning"
					)
					doc.create_receive_entry()
				doc.create_under_collection_entry(posting_date)
			
			elif new_status == ReceivableChequeStatus.COLLECTED and old_status != ReceivableChequeStatus.COLLECTED:
				# Mark as collected - create Collection JE
				# Bank account is required - use the one stored in the document
				if not doc.bank_account:
					frappe.throw("Bank Account is required. Please select a bank account before marking cheque as collected.")
				doc.create_collection_entry(posting_date=None, bank_account=doc.bank_account)
				# Submit the document if not already submitted
				if doc.docstatus == 0:
					doc.submit()
			
			elif new_status == ReceivableChequeStatus.RETURNED_FROM_BANK and old_status != ReceivableChequeStatus.RETURNED_FROM_BANK:
				# Mark as returned - create Return JE
				doc.create_return_entry()
				# Submit the document if not already submitted
				if doc.docstatus == 0:
					doc.submit()
			
			# Note: "Received From Customer" is the initial state (Doc Status 0 - Draft)
			# Journal Entry should only be created when moving to "Under Collection"
			# or other financial states, not when initially creating the cheque
		
		# Payable Cheque Journal Entry creation
		elif doc.cheque_type == ChequeType.PAYABLE:
			if new_status == PayableChequeStatus.ISSUED and old_status != PayableChequeStatus.ISSUED:
				# Issue cheque - create Payable Issue JE
				doc.create_payable_issue_entry(posting_date=None, bank_account=doc.bank_account)
				# Submit the document if not already submitted
				if doc.docstatus == 0:
					doc.submit()
			
			elif new_status == PayableChequeStatus.CLEARED and old_status != PayableChequeStatus.CLEARED:
				# Clear cheque - create Payable Clear JE
				doc.create_payable_clear_entry()
				# Submit the document if not already submitted
				if doc.docstatus == 0:
					doc.submit()
	
	except Exception as e:
		# Title must be ≤140 chars for Error Log
		frappe.log_error(title="Cheque Workflow JE Error", message=str(e))
		frappe.msgprint(f"Warning: Could not create Journal Entry automatically: {str(e)}", indicator="orange")


def before_cheque_delete(doc, method=None):
	"""
	Hook called before Cheque document is deleted
	Prevents deletion of submitted/finalized documents
	"""
	# Prevent deletion if document is submitted
	if doc.docstatus == 1:
		frappe.throw("Cannot delete a submitted Cheque document. Please cancel it first.", frappe.ValidationError)
	
	# Prevent deletion if document has Journal Entries
	if doc.journal_references and len(doc.journal_references) > 0:
		frappe.throw("Cannot delete a Cheque that has Journal Entries. Please cancel the Journal Entries first.", frappe.ValidationError)
	
	# Prevent deletion if in certain final states
	final_states = [
		ReceivableChequeStatus.COLLECTED,
		ReceivableChequeStatus.RETURN_TO_CUSTOMER,
		PayableChequeStatus.CLEARED,
		PayableChequeStatus.VOID,
	]
	
	if doc.status in final_states:
		frappe.throw(f"Cannot delete a Cheque in final state: {doc.status}", frappe.ValidationError)


def on_cheque_update_after_submit(doc, method=None):
	"""
	Hook called when Cheque document is updated after submission.
	Workflow uses workflow_state_field = "status", so workflow only updates doc.status.
	We must detect change via status, not workflow_state.
	"""
	if not hasattr(doc, "_doc_before_save") or not doc._doc_before_save:
		return

	# Workflow updates "status" field, not "workflow_state" - so compare status
	old_status = doc._doc_before_save.get("status") if doc._doc_before_save else None
	new_status = doc.get("status")
	if not new_status or old_status == new_status:
		return

	# Sync workflow_state with status (workflow_state_field is "status")
	if frappe.db.exists("Workflow State", new_status):
		doc.workflow_state = new_status

	# Create Journal Entry when status changes (e.g. to Under Collection)
	create_je_for_status_change(doc, old_status, new_status)

