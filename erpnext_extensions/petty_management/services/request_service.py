from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate, today

from erpnext_extensions.petty_management.services.holder_service import (
	sync_request_holder_fields,
	validate_petty_cash_account_company,
)
from erpnext_extensions.petty_management.utils import (
	employee_has_draft_pm_clearance,
	get_pm_settings,
)


def validate_request(doc: Document) -> None:
	holder = sync_request_holder_fields(doc)
	compute_totals(doc)
	sync_request_status_from_workflow(doc)

	settings = get_pm_settings()
	if not doc.details:
		frappe.throw(_("Add at least one detail line"))
	if flt(doc.total_requested_amount) <= 0:
		frappe.throw(_("Total Requested Amount must be greater than zero"))
	if holder.is_blocked:
		frappe.throw(_("This petty cash holder is blocked"))
	if (
		settings
		and settings.block_new_request_if_pending_clearance
		and employee_has_draft_pm_clearance(doc.employee, doc.company)
	):
		frappe.throw(_("This employee has a pending PM Clearance; new requests are blocked by settings."))

	if holder.get("max_balance") is not None:
		limit = flt(holder.max_balance)
		projected = flt(doc.previous_balance) + flt(doc.total_requested_amount)
		allow_over = bool(settings and settings.allow_negative_balance)
		if not allow_over and projected > limit + 1e-6:
			frappe.throw(_("Advance would exceed max balance {0} (projected {1}).").format(limit, projected))

	validate_payment_accounts(doc)


def compute_totals(doc: Document) -> None:
	total = 0.0
	for row in doc.details:
		total += flt(row.advance_amount)
	doc.total_requested_amount = total
	for row in doc.details:
		row.percent_of_total = (flt(row.advance_amount) / total * 100) if total else 0


def sync_request_status_from_workflow(doc: Document) -> None:
	if doc.payment_entry or (doc.payment_status or "") == "Paid" or (doc.status or "") == "Paid":
		return
	ws = doc.workflow_state
	if not ws:
		return
	ws_title = frappe.db.get_value("Workflow State", ws, "workflow_state_name") or ws
	mapping = {
		"Draft": "Draft",
		"Pending Approval": "Pending",
		"Approved": "Payable",
		"Rejected": "Rejected",
		"Cancelled": "Cancelled",
		"Paid": "Paid",
	}
	if ws_title in mapping:
		doc.status = mapping[ws_title]


def validate_payment_accounts(doc: Document) -> None:
	validate_petty_cash_account_company(doc.petty_cash_account, doc.company)
	if not doc.employee_bank_account:
		return
	ba = frappe.db.get_value(
		"Bank Account",
		doc.employee_bank_account,
		["party_type", "party", "company"],
		as_dict=True,
	)
	if not ba:
		return
	if ba.get("company") and ba["company"] != doc.company:
		frappe.throw(_("Employee Bank Account must belong to the same company as this request"))
	if ba.get("party_type") == "Employee" and ba.get("party") and ba["party"] != doc.employee:
		frappe.throw(_("Employee Bank Account must be for this request's employee"))


def validate_request_cancel(doc: Document) -> None:
	if doc.payment_entry and frappe.db.get_value("Payment Entry", doc.payment_entry, "docstatus") == 1:
		frappe.throw(_("Cancel the linked Payment Entry first"))
	if doc.journal_entry and frappe.db.get_value("Journal Entry", doc.journal_entry, "docstatus") == 1:
		frappe.throw(_("Cancel the linked Journal Entry first"))


def create_payment_entry(pm_request: str) -> str:
	doc = frappe.get_doc("PM Request", pm_request)
	if not frappe.has_permission("PM Request", "read", doc=doc):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	if doc.docstatus != 1:
		frappe.throw(_("Please submit PM Request before creating Payment Entry."))
	if not frappe.has_permission("PM Request", "submit", doc=doc):
		frappe.throw(_("Not permitted to create Payment Entry"), frappe.PermissionError)

	settings = get_pm_settings()
	if not doc.employee:
		frappe.throw(_("Employee is required"))
	if not doc.petty_cash_account:
		frappe.throw(_("Petty Cash Account is missing"))
	if doc.payment_entry or (doc.payment_status or "") == "Paid":
		frappe.throw(_("Payment Entry already exists or this request is already marked Paid"))

	ws_title = frappe.db.get_value("Workflow State", doc.workflow_state, "workflow_state_name") if doc.workflow_state else None
	payable = ws_title == "Approved" or (doc.status or "") in ("Payable", "Approved")
	if not payable:
		frappe.throw(_("Request must be workflow-approved and Payable before creating Payment Entry."))

	paid_from = settings.default_bank_account if settings else None
	if not paid_from:
		frappe.throw(_("Please configure Default Bank Account in PM Settings."))

	amount = flt(doc.total_requested_amount)
	if amount <= 0:
		frappe.throw(_("Total Requested Amount must be positive"))

	pe = _build_payment_entry(doc, paid_from, amount)
	try:
		pe.insert(ignore_permissions=True)
		if settings and settings.auto_submit_payment_entry:
			pe.submit()
	except Exception as e:
		frappe.db.rollback()
		frappe.throw(_("Payment Entry could not be created: {0}").format(str(e)), title=_("Payment Entry failed"))

	doc.db_set("payment_entry", pe.name, update_modified=False)
	doc.db_set("payment_status", "Paid", update_modified=False)
	doc.db_set("status", "Paid", update_modified=False)
	return pe.name


def _build_payment_entry(doc: Document, paid_from: str, amount: float) -> Document:
	company_currency = frappe.db.get_value("Company", doc.company, "default_currency")

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
	return pe

