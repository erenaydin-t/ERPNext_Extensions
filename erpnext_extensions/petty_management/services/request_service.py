from __future__ import annotations

import frappe
from frappe import _
from frappe.exceptions import QueryTimeoutError
from frappe.model.document import Document
from frappe.utils import cint, flt, getdate, today

from erpnext_extensions.petty_management.services.holder_service import (
	sync_request_holder_fields,
	validate_petty_cash_account_company,
)
from erpnext_extensions.petty_management.utils import (
	employee_has_draft_pm_clearance,
	get_pm_settings,
)


def workflow_state_title(doc: Document) -> str:
	if not getattr(doc, "workflow_state", None):
		return ""
	return (
		frappe.db.get_value("Workflow State", doc.workflow_state, "workflow_state_name") or doc.workflow_state or ""
	)


def reconcile_payment_entry_link(doc: Document) -> None:
	"""Clear stale Payment Entry links (missing or cancelled PE)."""
	if not getattr(doc, "payment_entry", None):
		return
	if not frappe.db.exists("Payment Entry", doc.payment_entry):
		doc.payment_entry = None
		return
	ds = cint(frappe.db.get_value("Payment Entry", doc.payment_entry, "docstatus"))
	if ds == 2:
		doc.payment_entry = None


def derive_payment_status(doc: Document) -> None:
	"""payment_status reflects accounting truth: Paid only when linked PE is submitted."""
	if not getattr(doc, "payment_entry", None):
		doc.payment_status = "Not Paid"
		return
	ds = cint(frappe.db.get_value("Payment Entry", doc.payment_entry, "docstatus"))
	doc.payment_status = "Paid" if ds == 1 else "Not Paid"


def validate_request(doc: Document) -> None:
	reconcile_payment_entry_link(doc)
	derive_payment_status(doc)

	holder = sync_request_holder_fields(doc)
	compute_totals(doc)
	sync_request_status_from_workflow(doc)
	enforce_request_state_machine(doc)

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


def enforce_request_state_machine(doc: Document) -> None:
	"""Disallow impossible combinations (rejected + funded, paid without PE, etc.)."""
	ws_title = workflow_state_title(doc)
	st = (doc.status or "").strip()
	rejected = ws_title == "Rejected" or st == "Rejected"

	if rejected:
		if doc.payment_entry:
			pe_ds = cint(frappe.db.get_value("Payment Entry", doc.payment_entry, "docstatus"))
			if pe_ds == 1:
				frappe.throw(
					_("Rejected PM Request cannot have a submitted Payment Entry. Cancel the Payment Entry first."),
					title=_("Invalid state"),
				)
			if pe_ds == 0:
				frappe.throw(
					_("Rejected PM Request cannot have a draft Payment Entry. Cancel the Payment Entry first."),
					title=_("Invalid state"),
				)

	if doc.payment_status == "Paid" and not doc.payment_entry:
		frappe.throw(_("Payment Status cannot be Paid without a Payment Entry."), title=_("Invalid state"))

	if doc.payment_entry:
		pe_ds = cint(frappe.db.get_value("Payment Entry", doc.payment_entry, "docstatus"))
		if pe_ds == 1 and doc.payment_status != "Paid":
			frappe.throw(_("Payment Status must be Paid when Payment Entry is submitted."), title=_("Invalid state"))
		if pe_ds != 1 and doc.payment_status == "Paid":
			frappe.throw(_("Payment Status Paid requires a submitted Payment Entry."), title=_("Invalid state"))


def compute_totals(doc: Document) -> None:
	total = 0.0
	for row in doc.details:
		total += flt(row.advance_amount)
	doc.total_requested_amount = total
	for row in doc.details:
		row.percent_of_total = (flt(row.advance_amount) / total * 100) if total else 0


def sync_request_status_from_workflow(doc: Document) -> None:
	"""Map workflow + accounting into status; rejected and paid are terminal for workflow mapping."""
	ws_title = workflow_state_title(doc)

	if ws_title == "Rejected" or (doc.status or "") == "Rejected":
		doc.status = "Rejected"
		return

	if doc.payment_status == "Paid":
		doc.status = "Paid"
		return

	if not ws_title:
		return

	mapping = {
		"Draft": "Draft",
		"Pending Approval": "Pending",
		"Pending": "Pending",
		"Pending Finance Review": "Pending",
		"Approved": "Payable",
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
	if getattr(doc, "journal_entry", None) and frappe.db.get_value("Journal Entry", doc.journal_entry, "docstatus") == 1:
		frappe.throw(_("Cancel the linked Journal Entry first"))
	from erpnext_extensions.petty_management.services.allocation_service import (
		clearance_reserves_pm_request_balance_sql,
	)

	res_clause = clearance_reserves_pm_request_balance_sql("cl")
	alloc_refs = frappe.db.sql(
		f"""
		select count(*) from `tabPM Clearance Request Allocation` a
		inner join `tabPM Clearance` cl on cl.name = a.parent and a.parenttype = 'PM Clearance'
		where a.parentfield = 'request_allocations'
			and ifnull(a.is_legacy_row, 0) = 0
			and a.pm_request = %s
			and {res_clause}
		""",
		doc.name,
	)[0][0]
	if alloc_refs:
		frappe.throw(
			_("Cannot cancel: this PM Request is still referenced on submitted PM Clearance allocation lines.")
		)


def request_ready_for_payment_entry(doc: Document) -> tuple[bool, str]:
	"""Single source of truth for funding eligibility."""
	if doc.docstatus != 1:
		return False, _("Submit the PM Request first.")
	reconcile_payment_entry_link(doc)
	derive_payment_status(doc)

	ws_title = workflow_state_title(doc)
	if ws_title == "Rejected" or (doc.status or "").strip() == "Rejected":
		return False, _("This request was rejected.")
	if ws_title != "Approved":
		return False, _("Payment Entry is only available after workflow approval (Approved state).")

	if doc.payment_status == "Paid":
		return False, _("This request is already funded.")
	if doc.payment_entry:
		ds = cint(frappe.db.get_value("Payment Entry", doc.payment_entry, "docstatus"))
		if ds == 0:
			return False, _("A draft Payment Entry already exists. Submit or cancel it before creating another.")
		if ds == 1:
			return False, _("A submitted Payment Entry already exists.")
	return True, ""


def find_active_payment_entries_for_pm_request(
	pm_request: str, *, exclude_pe: str | None = None
) -> list[str]:
	"""Non-cancelled Payment Entries tied to this PM Request (reference_no and/or custom_pm_request)."""
	names: set[str] = set(
		frappe.db.sql(
			"""
			select name from `tabPayment Entry`
			where reference_no = %s and docstatus in (0, 1)
			""",
			pm_request,
			pluck=True,
		)
	)
	meta_pe = frappe.get_meta("Payment Entry")
	if meta_pe.has_field("custom_pm_request"):
		for row in frappe.db.sql(
			"""
			select name from `tabPayment Entry`
			where custom_pm_request = %s and docstatus in (0, 1)
			""",
			pm_request,
			pluck=True,
		):
			names.add(row)
	if exclude_pe:
		names.discard(exclude_pe)
	return sorted(names)


def assert_no_active_payment_entry_for_request(doc: Document) -> None:
	"""Raise if another active PE already funds this request."""
	linked = (getattr(doc, "payment_entry", None) or "").strip()
	if linked and frappe.db.exists("Payment Entry", linked):
		ds = cint(frappe.db.get_value("Payment Entry", linked, "docstatus"))
		if ds in (0, 1):
			frappe.throw(
				_("A Payment Entry already exists for this PM Request ({0}).").format(linked),
				title=_("Duplicate funding Payment Entry"),
			)
	for pe_name in find_active_payment_entries_for_pm_request(doc.name, exclude_pe=linked or None):
		frappe.throw(
			_("Another Payment Entry already exists for this PM Request ({0}).").format(pe_name),
			title=_("Duplicate funding Payment Entry"),
		)


def _throw_payment_entry_busy() -> None:
	frappe.throw(
		_("This PM Request is currently being processed. Please refresh and try again."),
		title=_("Please try again"),
	)


def create_payment_entry(pm_request: str) -> str:
	"""Create funding PE with a short row lock on PM Request (validate/build outside the lock)."""
	doc = frappe.get_doc("PM Request", pm_request)
	if not frappe.has_permission("PM Request", "read", doc=doc):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	doc.check_permission("write")
	if doc.docstatus != 1:
		frappe.throw(_("Please submit PM Request before creating Payment Entry."))
	if not frappe.has_permission("PM Request", "submit", doc=doc):
		frappe.throw(_("Not permitted to create Payment Entry"), frappe.PermissionError)

	settings = get_pm_settings()
	if not doc.employee:
		frappe.throw(_("Employee is required"))
	if not doc.petty_cash_account:
		frappe.throw(_("Petty Cash Account is missing"))

	ok, reason = request_ready_for_payment_entry(doc)
	if not ok:
		frappe.throw(reason, title=_("Cannot create Payment Entry"))

	assert_no_active_payment_entry_for_request(doc)

	paid_from = settings.default_bank_account if settings else None
	if not paid_from:
		frappe.throw(_("Please configure Default Bank Account in PM Settings."))

	amount = flt(doc.total_requested_amount)
	if amount <= 0:
		frappe.throw(_("Total Requested Amount must be positive"))

	# Build PE (incl. narration templates) before acquiring PM Request row lock.
	pe = _build_payment_entry(doc, paid_from, amount)

	try:
		doc_locked = frappe.get_doc("PM Request", pm_request, for_update=True)
	except QueryTimeoutError:
		_throw_payment_entry_busy()

	try:
		ok, reason = request_ready_for_payment_entry(doc_locked)
		if not ok:
			frappe.throw(reason, title=_("Cannot create Payment Entry"))
		assert_no_active_payment_entry_for_request(doc_locked)

		pe.insert(ignore_permissions=True)
		from erpnext_extensions.petty_management.services.narration_service import (
			apply_funding_payment_entry_remarks,
		)

		apply_funding_payment_entry_remarks(pe, doc_locked, amount)
		pe.db_set(
			{"remarks": pe.remarks, "custom_remarks": 1 if frappe.get_meta("Payment Entry").has_field("custom_remarks") else 0},
			update_modified=False,
		)
		dupes = find_active_payment_entries_for_pm_request(doc_locked.name, exclude_pe=pe.name)
		if dupes:
			frappe.throw(
				_("Another Payment Entry already exists for this PM Request ({0}).").format(dupes[0]),
				title=_("Duplicate funding Payment Entry"),
			)

		doc_locked.db_set("payment_entry", pe.name, update_modified=False)
		doc_locked.payment_entry = pe.name
		derive_payment_status(doc_locked)
		sync_request_status_from_workflow(doc_locked)
		frappe.db.set_value(
			"PM Request",
			doc_locked.name,
			{"payment_status": doc_locked.payment_status, "status": doc_locked.status},
			update_modified=False,
		)
		frappe.db.commit()
	except QueryTimeoutError:
		frappe.db.rollback()
		_throw_payment_entry_busy()
	except Exception as e:
		frappe.db.rollback()
		frappe.throw(_("Payment Entry could not be created: {0}").format(str(e)), title=_("Payment Entry failed"))

	if settings and settings.auto_submit_payment_entry:
		try:
			apply_funding_payment_entry_remarks(pe, doc, amount)
			pe.db_set(
				{
					"remarks": pe.remarks,
					"custom_remarks": 1 if frappe.get_meta("Payment Entry").has_field("custom_remarks") else 0,
				},
				update_modified=False,
			)
			pe.submit()
		except Exception as e:
			frappe.db.rollback()
			frappe.throw(_("Payment Entry could not be submitted: {0}").format(str(e)), title=_("Payment Entry failed"))

	try:
		from erpnext_extensions.petty_management import petty_audit

		petty_audit.log_event(
			"pm_payment_entry_created",
			pm_request=doc.name,
			payment_entry=pe.name,
			holder=doc.holder,
			employee=doc.employee,
			amount=amount,
			company=doc.company,
			auto_submit=bool(settings and settings.auto_submit_payment_entry),
		)
	except Exception:
		pass
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

	meta_pe = frappe.get_meta("Payment Entry")
	if doc.employee_bank_account and meta_pe.has_field("party_bank_account"):
		pe.party_bank_account = doc.employee_bank_account

	from erpnext_extensions.petty_management.services.narration_service import (
		apply_funding_payment_entry_remarks,
	)

	apply_funding_payment_entry_remarks(pe, doc, amount)

	if meta_pe.has_field("custom_pm_request"):
		pe.custom_pm_request = doc.name
	if meta_pe.has_field("custom_pm_holder") and doc.holder:
		pe.custom_pm_holder = doc.holder
	return pe


def get_pm_request_action_flags(pm_request: str) -> dict:
	"""Desk UI: toolbar guards aligned with server rules."""
	doc = frappe.get_doc("PM Request", pm_request)
	if not frappe.has_permission("PM Request", "read", doc=doc):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	can_create, reason = request_ready_for_payment_entry(doc)
	can_open = bool(doc.payment_entry)
	return {
		"can_create_payment_entry": bool(can_create),
		"can_open_payment_entry": can_open,
		"reason": reason or "",
		"workflow_state_title": workflow_state_title(doc),
		"payment_status": doc.payment_status or "",
	}
