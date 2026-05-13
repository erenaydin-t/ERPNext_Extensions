from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, getdate, today

from erpnext_extensions.petty_management.services.allocation_service import validate_request_allocations
from erpnext_extensions.petty_management.services.constants import EPSILON, SETTLEMENT_PI, SETTLEMENT_SA
from erpnext_extensions.petty_management.services.holder_service import (
	clearance_petty_cash_account,
	get_holder_petty_cash_account,
	sync_clearance_holder_fields,
)
from erpnext_extensions.petty_management.utils import get_pm_settings


def before_validate_clearance(doc: Document) -> None:
	if doc.docstatus == 0:
		prune_empty_request_allocation_rows(doc)


def validate_clearance(doc: Document) -> None:
	doc.je_clearance_date = getdate(doc.transaction_date or today())
	sync_clearance_holder_fields(doc)
	ensure_petty_cash_account_filled(doc)
	normalize_settlement_types(doc)
	stamp_rows(doc)
	validate_details_not_empty(doc)
	validate_duplicate_settlement_targets(doc)
	validate_and_stamp_pi_rows(doc)
	validate_and_stamp_supplier_advance_rows(doc)
	calc_line_totals(doc)
	calc_parent_totals(doc)
	validate_request_allocations(doc)
	sync_clearance_status_from_workflow(doc)
	validate_clearance_policy(doc)


def validate_clearance_policy(doc: Document) -> None:
	settings = get_pm_settings()
	if not doc.request_allocations:
		frappe.throw(_("Add at least one PM Request allocation line"))
	if flt(doc.total_expense_amount) <= 0:
		frappe.throw(_("Total settlement amount must be greater than zero"))

	allow_neg = bool(settings and settings.allow_negative_balance)
	if not allow_neg and flt(doc.total_expense_amount) > flt(doc.pending_amount) + EPSILON:
		frappe.throw(_("Clearance total {0} exceeds available petty request balance {1}.").format(doc.total_expense_amount, doc.pending_amount))

	for row in doc.details:
		if settings and settings.require_attachment and not row.proof:
			frappe.throw(_("Row {0}: attachment is required by PM Settings").format(row.idx))
		if settings and settings.require_bill_no and not row.bill_no:
			frappe.throw(_("Row {0}: bill number is required by PM Settings").format(row.idx))


def ensure_petty_cash_account_filled(doc: Document) -> None:
	if doc.holder and not (doc.petty_cash_account or "").strip():
		doc.petty_cash_account = get_holder_petty_cash_account(doc.holder)


def normalize_settlement_types(doc: Document) -> None:
	for row in doc.details:
		if not (getattr(row, "settlement_type", None) or "").strip():
			row.settlement_type = SETTLEMENT_PI
		st = (row.settlement_type or SETTLEMENT_PI).strip()
		if st == SETTLEMENT_PI:
			row.purchase_order = None
			row.supplier_advance_account = None
		else:
			row.purchase_invoice = None
			row.outstanding_amount = 0
			row.reference_doctype = None


def on_submit_clearance(doc: Document) -> None:
	refreshed = frappe.get_doc("PM Clearance", doc.name)
	sync_clearance_status_from_workflow(refreshed)
	if refreshed.status:
		frappe.db.set_value("PM Clearance", doc.name, "status", refreshed.status, update_modified=False)


def before_cancel_clearance(doc: Document) -> None:
	if not doc.journal_entry:
		return
	try:
		je = frappe.get_doc("Journal Entry", doc.journal_entry)
		if je.docstatus == 1:
			je.cancel()
	except frappe.ValidationError:
		frappe.throw(_("Could not cancel linked Journal Entry {0}. Cancel or amend it first.").format(doc.journal_entry))


def on_cancel_clearance(doc: Document) -> None:
	frappe.db.set_value(
		"PM Clearance",
		doc.name,
		{"journal_entry": None, "purchase_invoice": None, "status": "Cancelled"},
		update_modified=False,
	)
	for row_name in frappe.get_all(
		"PM Clearance Detail",
		filters={"parent": doc.name, "parenttype": "PM Clearance"},
		pluck="name",
	):
		frappe.db.set_value(
			"PM Clearance Detail",
			row_name,
			{"generated_doctype": None, "generated_document": None},
			update_modified=False,
		)


def prune_empty_request_allocation_rows(doc: Document) -> None:
	for row in list(doc.get("request_allocations") or []):
		if getattr(row, "is_legacy_row", 0):
			continue
		has_req = bool((row.pm_request or "").strip())
		has_amt = flt(row.allocated_amount) != 0
		if not has_req and not has_amt:
			doc.remove(row)


def stamp_rows(doc: Document) -> None:
	for row in doc.details:
		if not row.created_by_user:
			row.created_by_user = frappe.session.user


def validate_details_not_empty(doc: Document) -> None:
	if not doc.details:
		frappe.throw(_("Add at least one settlement line"))


def validate_duplicate_settlement_targets(doc: Document) -> None:
	seen_pi = set()
	seen_po = set()
	for row in doc.details:
		st = (row.settlement_type or SETTLEMENT_PI).strip()
		if st == SETTLEMENT_PI:
			if not row.purchase_invoice:
				continue
			if row.purchase_invoice in seen_pi:
				frappe.throw(_("Purchase Invoice {0} cannot appear on more than one line.").format(row.purchase_invoice), title=_("Duplicate Purchase Invoice"))
			seen_pi.add(row.purchase_invoice)
		elif st == SETTLEMENT_SA:
			if not row.purchase_order:
				continue
			if row.purchase_order in seen_po:
				frappe.throw(_("Purchase Order {0} cannot appear on more than one line.").format(row.purchase_order), title=_("Duplicate Purchase Order"))
			seen_po.add(row.purchase_order)


def validate_and_stamp_pi_rows(doc: Document) -> None:
	for row in doc.details:
		if (row.settlement_type or SETTLEMENT_PI).strip() != SETTLEMENT_PI:
			continue
		if not row.purchase_invoice:
			frappe.throw(_("Row {0}: Purchase Invoice is required for Purchase Invoice settlement.").format(row.idx))
		if row.reference_doctype and row.reference_doctype != "Purchase Invoice":
			frappe.throw(_("Line {0}: only Purchase Invoice is supported for this settlement type.").format(row.idx))
		row.reference_doctype = "Purchase Invoice"
		pi = frappe.get_doc("Purchase Invoice", row.purchase_invoice)
		if pi.docstatus != 1:
			frappe.throw(_("Row {0}: Purchase Invoice must be submitted.").format(row.idx))
		if pi.company != doc.company:
			frappe.throw(_("Row {0}: Purchase Invoice belongs to another company.").format(row.idx))
		if flt(pi.outstanding_amount) <= 0:
			frappe.throw(_("Row {0}: Purchase Invoice has no outstanding amount to settle.").format(row.idx))
		row.supplier = pi.supplier
		row.outstanding_amount = flt(pi.outstanding_amount)
		if flt(row.allocated_amount) <= 0:
			row.allocated_amount = flt(pi.outstanding_amount)
		if flt(row.allocated_amount) <= 0:
			frappe.throw(_("Row {0}: Allocated Amount must be greater than zero.").format(row.idx))
		if flt(row.allocated_amount) > flt(pi.outstanding_amount) + EPSILON:
			frappe.throw(_("Row {0}: allocated amount cannot exceed Purchase Invoice outstanding ({1}).").format(row.idx, pi.outstanding_amount))


def validate_and_stamp_supplier_advance_rows(doc: Document) -> None:
	for row in doc.details:
		if (row.settlement_type or SETTLEMENT_PI).strip() != SETTLEMENT_SA:
			continue
		if not row.purchase_order:
			frappe.throw(_("Row {0}: Purchase Order is required for Supplier Advance.").format(row.idx))
		if not row.supplier_advance_account:
			frappe.throw(_("Row {0}: Supplier Advance Account is required.").format(row.idx))
		po = frappe.get_doc("Purchase Order", row.purchase_order)
		if po.docstatus != 1:
			frappe.throw(_("Row {0}: Purchase Order must be submitted.").format(row.idx))
		if po.company != doc.company:
			frappe.throw(_("Row {0}: Purchase Order belongs to another company.").format(row.idx))
		row.supplier = po.supplier
		acc_co = frappe.db.get_value("Account", row.supplier_advance_account, "company")
		if acc_co and acc_co != doc.company:
			frappe.throw(_("Row {0}: Supplier Advance Account must belong to the clearance company.").format(row.idx))
		if flt(row.allocated_amount) <= 0:
			frappe.throw(_("Row {0}: Allocated Amount must be greater than zero.").format(row.idx))


def calc_line_totals(doc: Document) -> None:
	for row in doc.details:
		row.amount_plus_tax = flt(row.allocated_amount)


def calc_parent_totals(doc: Document) -> None:
	total = sum(flt(row.allocated_amount) for row in doc.details)
	doc.total_expense_without_tax = 0
	doc.total_tax_amount = 0
	doc.total_expense_amount = total
	doc.total_petty_cash = total
	doc.remaining_amount = flt(doc.pending_amount) - flt(doc.total_expense_amount)


def sync_clearance_status_from_workflow(doc: Document) -> None:
	if doc.journal_entry:
		je_ds = frappe.db.get_value("Journal Entry", doc.journal_entry, "docstatus")
		if cint(je_ds) == 1:
			doc.status = "Settled"
		elif cint(je_ds) == 0:
			doc.status = "Pending Journal Entry Submission"
		else:
			doc.status = "Cancelled"
		return
	ws = doc.workflow_state
	if not ws:
		return
	ws_title = frappe.db.get_value("Workflow State", ws, "workflow_state_name") or ws
	mapping = {
		"Draft": "Draft",
		"Pending Finance Review": "Pending Finance Review",
		"Approved": "Approved",
		"Rejected": "Rejected",
		"Pending Journal Entry Submission": "Pending Journal Entry Submission",
	}
	if ws_title in mapping:
		doc.status = mapping[ws_title]


def clearance_is_approved(doc: Document) -> bool:
	if (getattr(doc, "status", None) or "").strip() == "Approved":
		return True
	ws = (getattr(doc, "workflow_state", None) or "").strip()
	if ws == "Approved":
		return True
	if ws and (frappe.db.get_value("Workflow State", ws, "workflow_state_name") or ws) == "Approved":
		return True
	return False


def prepare_doc_for_je_preview(doc: Document) -> None:
	sync_clearance_holder_fields(doc)
	ensure_petty_cash_account_filled(doc)
	normalize_settlement_types(doc)
	validate_duplicate_settlement_targets(doc)
	validate_and_stamp_pi_rows(doc)
	validate_and_stamp_supplier_advance_rows(doc)
	calc_line_totals(doc)
	calc_parent_totals(doc)
	validate_request_allocations(doc)

