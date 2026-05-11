# Copyright (c) 2026, Farbod Siyahpoosh and contributors
# For license information, please see license.txt

from __future__ import annotations

import copy
from typing import Any

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.model.naming import getseries
from frappe.utils import cint, flt, getdate, today

from erpnext.accounts.utils import get_balance_on

from erpnext_extensions.petty_management.utils import (
	get_pm_holder_name,
	get_pm_settings,
)

_EPS = 1e-6

SETTLEMENT_PI = "Purchase Invoice"
SETTLEMENT_SA = "Supplier Advance"


def _petty_cash_account_for_holder(holder_name: str | None) -> str:
	if not holder_name:
		return ""
	return frappe.db.get_value("PM Holder", holder_name, "petty_cash_account") or ""


def clearance_petty_cash_account(doc: Document) -> str:
	"""Authoritative petty cash account for the clearance (avoids stale/empty link fields)."""
	if getattr(doc, "petty_cash_account", None):
		return (doc.petty_cash_account or "").strip()
	if getattr(doc, "holder", None):
		return _petty_cash_account_for_holder(doc.holder)
	return ""


def pm_request_petty_cash_from_holder(pm_request_doc: Document) -> str:
	"""Petty cash account from PM Request's employee/company holder (not cached JSON on PM Request)."""
	h = get_pm_holder_name(pm_request_doc.employee, pm_request_doc.company)
	return _petty_cash_account_for_holder(h)


def get_pm_request_paid_amount(pm_request: str) -> float:
	"""Company-currency amount advanced to petty for this PM Request (submitted Payment Entry only)."""
	req = frappe.db.get_value(
		"PM Request",
		pm_request,
		["payment_entry", "payment_status", "total_requested_amount"],
		as_dict=True,
	)
	if not req:
		return 0.0
	pe_name = req.payment_entry
	if not pe_name:
		return 0.0
	pe = frappe.db.get_value(
		"Payment Entry",
		pe_name,
		["docstatus", "paid_amount", "received_amount"],
		as_dict=True,
	)
	if not pe or cint(pe.docstatus) != 1:
		return 0.0
	for fieldname in ("paid_amount", "received_amount"):
		if flt(pe.get(fieldname)) > 0:
			return flt(pe.get(fieldname))
	if (req.payment_status or "").strip() == "Paid":
		return flt(req.total_requested_amount)
	return 0.0


def sum_prior_pm_request_allocations(pm_request: str, exclude_clearance_name: str | None) -> float:
	"""Sum allocated_amount on other submitted clearances for this request (excludes legacy rows)."""
	params: list[Any] = [pm_request]
	excl_sql = ""
	if exclude_clearance_name:
		excl_sql = " AND p.name != %s "
		params.append(exclude_clearance_name)

	tot = frappe.db.sql(
		f"""
		SELECT COALESCE(SUM(c.allocated_amount), 0)
		FROM `tabPM Clearance Request Allocation` c
		INNER JOIN `tabPM Clearance` p ON p.name = c.parent AND c.parenttype = 'PM Clearance'
		WHERE c.parentfield = 'request_allocations'
			AND IFNULL(c.is_legacy_row, 0) = 0
			AND c.pm_request = %s
			AND p.docstatus = 1
			AND IFNULL(p.status, '') != 'Cancelled'
			{excl_sql}
		""",
		tuple(params),
	)[0][0]
	return flt(tot)


def pm_request_passes_clearance_filters(
	pm_request_name: str,
	*,
	employee: str,
	company: str,
	holder: str,
	clearance_petty: str,
) -> tuple[bool, str]:
	"""Eligibility for PM Clearance allocation (paid / submitted PE / same holder / petty match)."""
	if not pm_request_name:
		return False, _("PM Request is empty")
	req = frappe.get_doc("PM Request", pm_request_name)
	if req.docstatus != 1:
		return False, _("PM Request must be submitted")
	if req.company != company:
		return False, _("PM Request belongs to another company")
	if req.employee != employee:
		return False, _("PM Request belongs to another employee")
	if (req.holder or "") != (holder or ""):
		return False, _("PM Request belongs to another PM Holder")
	req_petty = pm_request_petty_cash_from_holder(req)
	clr_petty = (clearance_petty or "").strip()
	if req_petty != clr_petty:
		return False, _("PM Request petty cash account does not match this clearance holder")
	if not req.payment_entry:
		return False, _("PM Request {0} has no submitted Payment Entry. Please create/submit Payment Entry first.").format(pm_request_name)
	if frappe.db.get_value("Payment Entry", req.payment_entry, "docstatus") != 1:
		return False, _("PM Request {0} has no submitted Payment Entry. Please create/submit Payment Entry first.").format(pm_request_name)
	ps = (req.payment_status or "").strip()
	if ps != "Paid":
		return False, _("PM Request payment status must be Paid with a submitted Payment Entry")
	paid = get_pm_request_paid_amount(pm_request_name)
	if paid <= 0:
		return False, _("PM Request {0} has no submitted Payment Entry. Please create/submit Payment Entry first.").format(pm_request_name)
	return True, ""


def build_clearance_je_accounts(doc: Document) -> list[dict[str, Any]]:
	"""Build Journal Entry `accounts` rows: Dr PI payable and/or Dr supplier advance, Cr petty cash.

	Single source of truth for settlement posting and preview. No PM Request rows.
	Purchase Order is a valid ``reference_type`` on Journal Entry Account in ERPNext.
	"""
	lines: list[dict[str, Any]] = []
	total_petty_credit = 0.0

	for row in doc.details:
		st = (getattr(row, "settlement_type", None) or SETTLEMENT_PI).strip()
		alloc = flt(row.allocated_amount)
		cc = row.cost_center or None
		prj = row.project or doc.project or None

		if st == SETTLEMENT_SA:
			if not row.supplier_advance_account:
				frappe.throw(
					_("Row {0}: Supplier Advance Account is required for Supplier Advance.").format(row.idx)
				)
			line = {
				"account": row.supplier_advance_account,
				"party_type": "Supplier",
				"party": row.supplier,
				"reference_type": "Purchase Order",
				"reference_name": row.purchase_order,
				"debit_in_account_currency": alloc,
				"credit_in_account_currency": 0,
			}
		else:
			pi = frappe.get_doc("Purchase Invoice", row.purchase_invoice)
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
		lines.append(line)
		total_petty_credit += alloc

	petty = clearance_petty_cash_account(doc)
	if not petty:
		frappe.throw(_("Petty Cash Account is missing on this clearance."))
	credit_line = {
		"account": petty,
		"debit_in_account_currency": 0,
		"credit_in_account_currency": total_petty_credit,
	}
	if frappe.db.get_value("Account", petty, "account_type") in ("Receivable", "Payable"):
		# ERPNext enforces party dimensions for Receivable/Payable ledgers, even when used as holder petty.
		credit_line.update({"party_type": "Employee", "party": doc.employee})
	lines.append(credit_line)
	return lines


def _clearance_is_approved(doc: Document) -> bool:
	"""Demo-safe approval gate: accept either workflow title/value or synced status."""
	if (getattr(doc, "status", None) or "").strip() == "Approved":
		return True
	ws = (getattr(doc, "workflow_state", None) or "").strip()
	if ws == "Approved":
		return True
	if ws and (frappe.db.get_value("Workflow State", ws, "workflow_state_name") or ws) == "Approved":
		return True
	return False


class PMClearance(Document):
	"""Settlement container: settlement lines (PI and/or supplier advance) + PM Request allocation (control)."""

	def autoname(self):
		if not self.employee:
			frappe.throw(_("Employee is required before naming"))
		d = getdate(self.transaction_date or today())
		emp_key = str(self.employee).replace(" ", "")[:40]
		prefix = f"CLR-{emp_key}-{d.year}-{d.month:02d}-"
		self.name = prefix + getseries(prefix, 5)

	def before_validate(self):
		if self.docstatus == 0:
			self._prune_empty_request_allocation_rows()

	def validate(self):
		self.je_clearance_date = getdate(self.transaction_date or today())
		# 1–2: holder + petty always synced before line / allocation validation
		self._sync_holder_and_pending()
		self._ensure_petty_cash_account_filled()
		self._normalize_settlement_types()
		self._stamp_rows()
		self._validate_details_not_empty()
		self._validate_duplicate_settlement_targets()
		# 3–4: stamp settlement lines then totals
		self._validate_and_stamp_pi_rows()
		self._validate_and_stamp_supplier_advance_rows()
		self._calc_line_totals()
		self._calc_parent_totals()
		# 5: PM Request allocation (snapshots + caps + equality)
		self._validate_request_allocations()
		self._sync_clearance_status_from_workflow()
		self._sync_funding_traceability_snapshot()
		settings = get_pm_settings()

		if not self.request_allocations:
			frappe.throw(_("Add at least one PM Request allocation line"))

		if flt(self.total_expense_amount) <= 0:
			frappe.throw(_("Total settlement amount must be greater than zero"))

		allow_neg = bool(settings and settings.allow_negative_balance)
		if not allow_neg and flt(self.total_expense_amount) > flt(self.pending_amount) + _EPS:
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

	def _ensure_petty_cash_account_filled(self):
		"""Avoid false petty mismatch when the link field was empty before holder sync."""
		if self.holder and not (self.petty_cash_account or "").strip():
			self.petty_cash_account = _petty_cash_account_for_holder(self.holder)

	def _normalize_settlement_types(self):
		for row in self.details:
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

	def before_submit(self):
		return

	def on_submit(self):
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

	def _prune_empty_request_allocation_rows(self):
		"""Draft-only: drop allocation rows with no PM Request and no amount (avoids mandatory-field noise on Save)."""
		for row in list(self.get("request_allocations") or []):
			if getattr(row, "is_legacy_row", 0):
				continue
			has_req = bool((row.pm_request or "").strip())
			has_amt = flt(row.allocated_amount) != 0
			if not has_req and not has_amt:
				self.remove(row)

	def _sync_holder_and_pending(self):
		hname = get_pm_holder_name(self.employee, self.company)
		self.holder = hname
		if not self.holder:
			frappe.throw(
				_(
					"No PM Holder found for this employee and company. Please create PM Holder first."
				)
			)
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
		self.current_petty_balance = flt(self.pending_amount)
		if not self.holder:
			return
		hb = frappe.db.get_value(
			"PM Holder",
			self.holder,
			["current_balance", "consumed_amount", "pending_clearance_amount"],
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

	def _validate_details_not_empty(self):
		if not self.details:
			frappe.throw(_("Add at least one settlement line"))

	def _validate_duplicate_settlement_targets(self):
		seen_pi = set()
		seen_po = set()
		for row in self.details:
			st = (row.settlement_type or SETTLEMENT_PI).strip()
			if st == SETTLEMENT_PI:
				if not row.purchase_invoice:
					continue
				if row.purchase_invoice in seen_pi:
					frappe.throw(
						_("Purchase Invoice {0} cannot appear on more than one line.").format(
							row.purchase_invoice
						),
						title=_("Duplicate Purchase Invoice"),
					)
				seen_pi.add(row.purchase_invoice)
			elif st == SETTLEMENT_SA:
				if not row.purchase_order:
					continue
				if row.purchase_order in seen_po:
					frappe.throw(
						_("Purchase Order {0} cannot appear on more than one line.").format(
							row.purchase_order
						),
						title=_("Duplicate Purchase Order"),
					)
				seen_po.add(row.purchase_order)

	def _validate_and_stamp_pi_rows(self):
		for row in self.details:
			if (row.settlement_type or SETTLEMENT_PI).strip() != SETTLEMENT_PI:
				continue
			if not row.purchase_invoice:
				frappe.throw(_("Row {0}: Purchase Invoice is required for Purchase Invoice settlement.").format(row.idx))
			if row.reference_doctype and row.reference_doctype != "Purchase Invoice":
				frappe.throw(
					_("Line {0}: only Purchase Invoice is supported for this settlement type.").format(row.idx),
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
			if flt(row.allocated_amount) > flt(pi.outstanding_amount) + _EPS:
				frappe.throw(
					_("Row {0}: allocated amount cannot exceed Purchase Invoice outstanding ({1}).").format(
						row.idx, pi.outstanding_amount
					),
				)

	def _validate_and_stamp_supplier_advance_rows(self):
		for row in self.details:
			if (row.settlement_type or SETTLEMENT_PI).strip() != SETTLEMENT_SA:
				continue
			if not row.purchase_order:
				frappe.throw(_("Row {0}: Purchase Order is required for Supplier Advance.").format(row.idx))
			if not row.supplier_advance_account:
				frappe.throw(_("Row {0}: Supplier Advance Account is required.").format(row.idx))
			po = frappe.get_doc("Purchase Order", row.purchase_order)
			if po.docstatus != 1:
				frappe.throw(_("Row {0}: Purchase Order must be submitted.").format(row.idx))
			if po.company != self.company:
				frappe.throw(_("Row {0}: Purchase Order belongs to another company.").format(row.idx))
			row.supplier = po.supplier
			acc_co = frappe.db.get_value("Account", row.supplier_advance_account, "company")
			if acc_co and acc_co != self.company:
				frappe.throw(_("Row {0}: Supplier Advance Account must belong to the clearance company.").format(row.idx))
			if flt(row.allocated_amount) <= 0:
				frappe.throw(_("Row {0}: Allocated Amount must be greater than zero.").format(row.idx))

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

	def _validate_request_allocations(self):
		clr_petty = clearance_petty_cash_account(self)
		if not clr_petty and self.holder:
			clr_petty = _petty_cash_account_for_holder(self.holder)
			self.petty_cash_account = clr_petty

		legacy_rows = [r for r in self.request_allocations if r.is_legacy_row]
		non_legacy = [r for r in self.request_allocations if not r.is_legacy_row]

		if legacy_rows and non_legacy:
			frappe.throw(
				_("Cannot mix legacy PM Request allocation rows with standard allocation rows."),
				title=_("PM Request allocation"),
			)

		if legacy_rows:
			if not self.name:
				frappe.throw(_("Save the document before using legacy allocation data."))
			had_legacy_in_db = frappe.db.sql(
				"""
				select count(*) from `tabPM Clearance Request Allocation`
				where parent = %s
					and parenttype = 'PM Clearance'
					and parentfield = 'request_allocations'
					and ifnull(is_legacy_row, 0) = 1
				""",
				(self.name,),
			)[0][0]
			if not had_legacy_in_db:
				frappe.throw(
					_("Legacy PM Request allocation rows are created only during data migration."),
					title=_("PM Request allocation"),
				)
			if len(self.request_allocations) != 1 or len(legacy_rows) != 1:
				frappe.throw(
					_("Legacy clearance must have exactly one legacy PM Request allocation row."),
					title=_("PM Request allocation"),
				)
			lr = legacy_rows[0]
			if lr.pm_request:
				frappe.throw(_("Legacy allocation row must not reference a PM Request."))
			if abs(flt(lr.allocated_amount) - flt(self.total_expense_amount)) > _EPS:
				frappe.throw(
					_("Legacy allocated amount must equal total settlement amount ({0}).").format(
						self.total_expense_amount
					)
				)
			lr.request_amount = 0.0
			lr.paid_amount = 0.0
			lr.previously_allocated_amount = 0.0
			lr.available_amount = 0.0
			return

		seen_req = set()
		sum_alloc = 0.0
		for row in self.request_allocations:
			if getattr(row, "is_legacy_row", 0):
				continue
			has_req = bool((row.pm_request or "").strip())
			has_amt = flt(row.allocated_amount) > 0
			if not has_req and not has_amt:
				continue
			if has_req != has_amt:
				frappe.throw(
					_(
						"Row {0}: Please select PM Request and Allocated Amount, or remove the empty allocation row."
					).format(row.idx),
					title=_("PM Request allocation"),
				)
			if row.pm_request in seen_req:
				frappe.throw(
					_("PM Request {0} cannot appear on more than one line.").format(row.pm_request),
					title=_("Duplicate PM Request"),
				)
			seen_req.add(row.pm_request)

			req = frappe.get_doc("PM Request", row.pm_request)
			req_petty = pm_request_petty_cash_from_holder(req)
			if req.employee != self.employee:
				frappe.throw(
					_(
						"Row {0}: PM Request {1} is for employee {2}; this clearance is for employee {3}."
					).format(row.idx, row.pm_request, req.employee, self.employee),
					title=_("PM Request mismatch"),
				)
			if req.company != self.company:
				frappe.throw(
					_("Row {0}: PM Request {1} belongs to company {2}; clearance company is {3}.").format(
						row.idx, row.pm_request, req.company, self.company
					),
					title=_("PM Request mismatch"),
				)
			if (req.holder or "") != (self.holder or ""):
				frappe.throw(
					_(
						"Row {0}: PM Request {1} holder {2} does not match clearance holder {3}."
					).format(row.idx, row.pm_request, req.holder or "—", self.holder or "—"),
					title=_("PM Request mismatch"),
				)
			if (req_petty or "").strip() != (clr_petty or "").strip():
				req_acct_disp = req_petty or _("(empty)")
				clr_acct_disp = clr_petty or _("(empty)")
				frappe.throw(
					_(
						"Row {0}: PM Request {1} advances petty cash account {2}, but this clearance uses {3}. "
						"Select a PM Request for the same employee and holder. "
						"(Clearance employee: {4}, request employee: {5}; clearance holder: {6}, request holder: {7})"
					).format(
						row.idx,
						row.pm_request,
						req_acct_disp,
						clr_acct_disp,
						self.employee,
						req.employee,
						self.holder or "—",
						req.holder or "—",
					),
					title=_("Petty cash account mismatch"),
				)

			ok, reason = pm_request_passes_clearance_filters(
				row.pm_request,
				employee=self.employee,
				company=self.company,
				holder=self.holder or "",
				clearance_petty=clr_petty,
			)
			if not ok:
				frappe.throw(_("Row {0}: {1}").format(row.idx, reason))

			ctx = get_pm_request_allocation_context(
				row.pm_request,
				pm_clearance=self.name if getattr(self, "name", None) else None,
				company=self.company,
				employee=self.employee,
				holder=self.holder or "",
				petty_cash_account=clr_petty,
			)
			row.request_amount = flt(ctx.get("request_amount"))
			row.paid_amount = flt(ctx.get("paid_amount"))
			if row.paid_amount <= 0:
				frappe.throw(
					_("Row {0}: PM Request {1} has no submitted Payment Entry. Please create/submit Payment Entry first.").format(row.idx, row.pm_request)
				)
			row.previously_allocated_amount = flt(ctx.get("previously_allocated_amount"))
			row.available_amount = flt(ctx.get("available_amount"))
			if flt(row.allocated_amount) <= 0:
				frappe.throw(_("Row {0}: Allocated Amount must be greater than zero.").format(row.idx))
			if flt(row.allocated_amount) > flt(row.available_amount) + _EPS:
				frappe.throw(
					_(
						"Row {0}: allocated {1} exceeds available PM Request balance {2} for {3}."
					).format(row.idx, row.allocated_amount, row.available_amount, row.pm_request)
				)
			sum_alloc += flt(row.allocated_amount)

		if abs(sum_alloc - flt(self.total_expense_amount)) > _EPS:
			frappe.throw(
				_(
					"Total PM Request allocation ({0}) must equal total settlement lines amount ({1})."
				).format(sum_alloc, self.total_expense_amount),
				title=_("Settlement totals"),
			)

	def _sync_clearance_status_from_workflow(self):
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
			"Rejected": "Rejected",
		}
		if ws_title in m:
			self.status = m[ws_title]

	def _create_clearance_journal_entry(self):
		settings = get_pm_settings()
		je = frappe.new_doc("Journal Entry")
		je.company = self.company
		je.voucher_type = "Journal Entry"
		je.posting_date = getdate(self.je_clearance_date or self.transaction_date or today())
		je.user_remark = _("Petty cash clearance {0}").format(self.name)

		meta = frappe.get_meta("Journal Entry")
		if meta.has_field("custom_pm_clearance"):
			je.custom_pm_clearance = self.name
		if meta.has_field("custom_pm_holder") and self.holder:
			je.custom_pm_holder = self.holder

		for line in build_clearance_je_accounts(self):
			je.append("accounts", line)

		je.insert(ignore_permissions=True)
		if settings and settings.auto_submit_journal_entry:
			je.submit()
		return je


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def pm_request_query_for_pm_clearance(
	doctype,
	txt,
	searchfield,
	start,
	page_len,
	filters,
):
	"""Link search: PM Requests usable on this clearance (same holder/petty, paid PE, available > 0)."""
	if doctype != "PM Request":
		return []
	if isinstance(filters, str):
		filters = frappe.parse_json(filters) if filters else {}
	filters = filters or {}
	employee = filters.get("employee")
	company = filters.get("company")
	holder = filters.get("holder")
	petty = (filters.get("petty_cash_account") or "").strip()
	if not employee or not company or not holder or not petty:
		return []

	txt_cond = ""
	values: dict[str, Any] = {
		"employee": employee,
		"company": company,
		"holder": holder,
		"petty": petty,
		"txt": f"%{txt}%",
		"start": cint(start),
		"page_len": cint(page_len),
	}
	if txt:
		txt_cond = """
			AND (
				pr.name LIKE %(txt)s
				OR pr.employee_name LIKE %(txt)s
				OR pr.holder LIKE %(txt)s
			)
		"""

	rows = frappe.db.sql(
		f"""
		SELECT pr.name
		FROM `tabPM Request` pr
		INNER JOIN `tabPM Holder` h ON h.name = pr.holder
		WHERE pr.docstatus = 1
			AND IFNULL(h.is_blocked, 0) = 0
			AND pr.company = %(company)s
			AND pr.employee = %(employee)s
			AND pr.holder = %(holder)s
			AND IFNULL(h.petty_cash_account, '') = %(petty)s
			AND IFNULL(pr.payment_entry, '') != ''
			AND IFNULL(pr.payment_status, '') = 'Paid'
			AND EXISTS (
				SELECT 1 FROM `tabPayment Entry` pe
				WHERE pe.name = pr.payment_entry AND pe.docstatus = 1
			)
			{txt_cond}
		ORDER BY pr.modified DESC
		LIMIT %(page_len)s OFFSET %(start)s
		""",
		values,
		as_dict=False,
	)
	names = [r[0] for r in rows]
	out = []
	for name in names:
		paid = get_pm_request_paid_amount(name)
		prev = sum_prior_pm_request_allocations(name, filters.get("pm_clearance") or None)
		if flt(paid) - flt(prev) > _EPS:
			out.append([name])
	return out


@frappe.whitelist()
def get_pm_request_allocation_context(
	pm_request: str,
	pm_clearance: str | None = None,
	company: str | None = None,
	employee: str | None = None,
	holder: str | None = None,
	petty_cash_account: str | None = None,
) -> dict[str, Any]:
	if not pm_request:
		return {}
	if not frappe.has_permission("PM Request", "read", pm_request):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	exclude_clearance = pm_clearance if pm_clearance and frappe.db.exists("PM Clearance", pm_clearance) else None
	if pm_clearance and frappe.db.exists("PM Clearance", pm_clearance):
		cl = frappe.get_doc("PM Clearance", pm_clearance)
		if not frappe.has_permission("PM Clearance", "read", doc=cl):
			frappe.throw(_("Not permitted"), frappe.PermissionError)
		cl._sync_holder_and_pending()
		cl._ensure_petty_cash_account_filled()
		company = cl.company
		employee = cl.employee
		holder = cl.holder or ""
		petty_cash_account = clearance_petty_cash_account(cl)

	req = frappe.get_doc("PM Request", pm_request)
	req_holder = req.holder or get_pm_holder_name(req.employee, req.company) or ""
	req_petty = _petty_cash_account_for_holder(req_holder)

	if company and req.company != company:
		frappe.throw(_("PM Request belongs to another company"), title=_("Invalid PM Request"))
	if employee and req.employee != employee:
		frappe.throw(_("PM Request belongs to another employee"), title=_("Invalid PM Request"))
	if holder and req_holder != holder:
		frappe.throw(_("PM Request belongs to another PM Holder"), title=_("Invalid PM Request"))
	if petty_cash_account and req_petty != (petty_cash_account or "").strip():
		frappe.throw(
			_("PM Request petty cash account does not match this clearance holder"),
			title=_("Invalid PM Request"),
		)

	ok, msg = pm_request_passes_clearance_filters(
		pm_request,
		employee=employee or req.employee,
		company=company or req.company,
		holder=holder or req_holder,
		clearance_petty=(petty_cash_account or req_petty or "").strip(),
	)
	if not ok:
		frappe.throw(msg, title=_("Invalid PM Request"))

	paid = get_pm_request_paid_amount(pm_request)
	prev = sum_prior_pm_request_allocations(pm_request, exclude_clearance)
	avail = flt(paid) - flt(prev)
	return {
		"pm_request": pm_request,
		"request_amount": flt(req.total_requested_amount),
		"paid_amount": paid,
		"previously_allocated_amount": prev,
		"available_amount": avail,
		"employee": req.employee,
		"holder": req_holder,
		"petty_cash_account": req_petty,
		"company": req.company,
	}


def _doc_for_preview(doc=None, pm_clearance: str | None = None) -> Document:
	if pm_clearance:
		d = frappe.get_doc("PM Clearance", pm_clearance)
		if not frappe.has_permission("PM Clearance", "read", doc=d):
			frappe.throw(_("Not permitted"), frappe.PermissionError)
		return d
	if not doc:
		frappe.throw(_("Document or PM Clearance name required"))
	raw = frappe.parse_json(doc)
	dobj = frappe.get_doc(raw)
	docname = getattr(dobj, "name", None)
	if docname and frappe.db.exists("PM Clearance", docname):
		if not frappe.has_permission("PM Clearance", "read", doc=docname):
			frappe.throw(_("Not permitted"), frappe.PermissionError)
	else:
		if not frappe.has_permission("PM Clearance", "create"):
			frappe.throw(_("Not permitted"), frappe.PermissionError)
	return dobj


def _prepare_doc_for_je_preview(dobj: Document) -> None:
	"""Rebuild settlement lines and allocations for preview on an isolated in-memory document."""
	dobj._sync_holder_and_pending()
	dobj._ensure_petty_cash_account_filled()
	dobj._normalize_settlement_types()
	dobj._validate_duplicate_settlement_targets()
	dobj._validate_and_stamp_pi_rows()
	dobj._validate_and_stamp_supplier_advance_rows()
	dobj._calc_line_totals()
	dobj._calc_parent_totals()
	dobj._validate_request_allocations()


@frappe.whitelist()
def preview_pm_clearance_settlement(doc=None, pm_clearance: str | None = None) -> dict[str, Any]:
	source_doc = _doc_for_preview(doc=doc, pm_clearance=pm_clearance)
	dobj = frappe.get_doc(copy.deepcopy(source_doc.as_dict()))
	_prepare_doc_for_je_preview(dobj)
	accounts = build_clearance_je_accounts(dobj)
	total_credit = sum(flt(a.get("credit_in_account_currency")) for a in accounts)
	total_debit = sum(flt(a.get("debit_in_account_currency")) for a in accounts)
	return {
		"accounts": accounts,
		"total_debit": total_debit,
		"total_credit": total_credit,
		"company": dobj.company,
		"posting_date": str(getdate(dobj.je_clearance_date or dobj.transaction_date or today())),
	}


@frappe.whitelist()
def settle_petty_cash(pm_clearance: str) -> dict[str, str]:
	doc = frappe.get_doc("PM Clearance", pm_clearance)
	if not frappe.has_permission("PM Clearance", "read", doc=doc):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	doc.check_permission("write")
	if doc.docstatus != 1:
		frappe.throw(_("Please submit PM Clearance before settling."), title=_("Submit required"))

	if not _clearance_is_approved(doc):
		frappe.throw(_("Settle is only allowed when PM Clearance is Approved."), title=_("Approval required"))

	if doc.journal_entry:
		return {"journal_entry": doc.journal_entry, "status": doc.status or "Settled"}

	doc.reload()
	if not _clearance_is_approved(doc):
		frappe.throw(_("Settle is only allowed when PM Clearance is Approved."), title=_("Approval required"))
	doc.validate()

	try:
		je = doc._create_clearance_journal_entry()
		doc.db_set("journal_entry", je.name, update_modified=False)
		doc.db_set("status", "Settled", update_modified=False)

		for row in doc.details:
			frappe.db.set_value(
				row.doctype,
				row.name,
				{"generated_doctype": "Journal Entry", "generated_document": je.name},
				update_modified=False,
			)

		meta_pi = frappe.get_meta("Purchase Invoice")
		has_holder = meta_pi.has_field("custom_pm_holder")
		has_clearance = meta_pi.has_field("custom_pm_clearance")
		if has_holder or has_clearance:
			for row in doc.details:
				if (row.settlement_type or SETTLEMENT_PI).strip() != SETTLEMENT_PI:
					continue
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
	except Exception as e:
		frappe.db.rollback()
		frappe.throw(_("Could not create settlement Journal Entry: {0}").format(str(e)))

	return {"journal_entry": je.name, "status": "Settled"}
