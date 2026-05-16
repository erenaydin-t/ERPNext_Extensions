from __future__ import annotations

from typing import Any

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt

from erpnext_extensions.petty_management.services.holder_service import (
	clearance_petty_cash_account,
	get_holder_petty_cash_account,
	request_petty_cash_account,
)
from erpnext_extensions.petty_management.utils import get_pm_holder_name

_EPS = 1e-6


def clearance_reserves_pm_request_balance_sql(table_alias: str = "p") -> str:
	"""SQL predicate for clearances whose PM Request allocation rows reserve funding.

	Only submitted (docstatus 1) clearances reserve. Cancelled submissions (docstatus 2),
	Rejected/Cancelled status, and Cancelled/Rejected workflow states never reserve.
	Reservation requires approval lifecycle (status or workflow title Approved) or
	post-approval settlement states (Pending JE / Settled).
	"""
	p = table_alias
	return f"""
		{p}.docstatus = 1
		AND IFNULL({p}.status, '') NOT IN ('Cancelled', 'Rejected', 'Draft')
		AND NOT EXISTS (
			SELECT 1 FROM `tabWorkflow State` ws
			WHERE ws.name = {p}.workflow_state
			AND IFNULL(ws.workflow_state_name, '') IN ('Cancelled', 'Rejected')
		)
		AND (
			IFNULL({p}.status, '') IN ('Approved', 'Pending Journal Entry Submission', 'Settled')
			OR EXISTS (
				SELECT 1 FROM `tabWorkflow State` ws
				WHERE ws.name = {p}.workflow_state
				AND IFNULL(ws.workflow_state_name, '') = 'Approved'
			)
		)
	"""


def get_pm_request_paid_amount(pm_request: str) -> float:
	req = frappe.db.get_value(
		"PM Request",
		pm_request,
		["payment_entry", "payment_status", "total_requested_amount"],
		as_dict=True,
	)
	if not req or not req.payment_entry:
		return 0.0
	pe = frappe.db.get_value(
		"Payment Entry",
		req.payment_entry,
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
	params: list[Any] = [pm_request]
	excl_sql = ""
	if exclude_clearance_name:
		excl_sql = " AND p.name != %s "
		params.append(exclude_clearance_name)

	res_clause = clearance_reserves_pm_request_balance_sql("p")

	return flt(
		frappe.db.sql(
			f"""
			SELECT COALESCE(SUM(c.allocated_amount), 0)
			FROM `tabPM Clearance Request Allocation` c
			INNER JOIN `tabPM Clearance` p ON p.name = c.parent AND c.parenttype = 'PM Clearance'
			WHERE c.parentfield = 'request_allocations'
				AND IFNULL(c.is_legacy_row, 0) = 0
				AND c.pm_request = %s
				AND {res_clause}
				{excl_sql}
			""",
			tuple(params),
		)[0][0]
	)


def get_pm_request_available_amount(pm_request: str, exclude_clearance_name: str | None = None) -> float:
	return flt(get_pm_request_paid_amount(pm_request)) - flt(
		sum_prior_pm_request_allocations(pm_request, exclude_clearance_name)
	)


def pm_request_passes_clearance_filters(
	pm_request_name: str,
	*,
	employee: str,
	company: str,
	holder: str,
	clearance_petty: str,
) -> tuple[bool, str]:
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
	if request_petty_cash_account(req) != (clearance_petty or "").strip():
		return False, _("PM Request petty cash account does not match this clearance holder")
	if not req.payment_entry or frappe.db.get_value("Payment Entry", req.payment_entry, "docstatus") != 1:
		return False, _("PM Request {0} has no submitted Payment Entry. Please create/submit Payment Entry first.").format(pm_request_name)
	if (req.payment_status or "").strip() != "Paid":
		return False, _("PM Request payment status must be Paid with a submitted Payment Entry")
	if get_pm_request_paid_amount(pm_request_name) <= 0:
		return False, _("PM Request {0} has no submitted Payment Entry. Please create/submit Payment Entry first.").format(pm_request_name)
	return True, ""


def validate_request_allocations(doc: Document) -> None:
	clr_petty = clearance_petty_cash_account(doc)
	if not clr_petty and doc.holder:
		clr_petty = get_holder_petty_cash_account(doc.holder)
		doc.petty_cash_account = clr_petty

	legacy_rows = [r for r in doc.request_allocations if r.is_legacy_row]
	non_legacy = [r for r in doc.request_allocations if not r.is_legacy_row]
	if legacy_rows and non_legacy:
		frappe.throw(_("Cannot mix legacy PM Request allocation rows with standard allocation rows."), title=_("PM Request allocation"))
	if legacy_rows:
		validate_legacy_allocation_rows(doc, legacy_rows)
		return

	seen_req = set()
	sum_alloc = 0.0
	for row in doc.request_allocations:
		if getattr(row, "is_legacy_row", 0):
			continue
		has_req = bool((row.pm_request or "").strip())
		has_amt = flt(row.allocated_amount) > 0
		if not has_req and not has_amt:
			continue
		if has_req != has_amt:
			frappe.throw(
				_("Row {0}: Please select PM Request and Allocated Amount, or remove the empty allocation row.").format(row.idx),
				title=_("PM Request allocation"),
			)
		if row.pm_request in seen_req:
			frappe.throw(_("PM Request {0} cannot appear on more than one line.").format(row.pm_request), title=_("Duplicate PM Request"))
		seen_req.add(row.pm_request)

		validate_pm_request_matches_clearance(row, doc, clr_petty)
		stamp_allocation_snapshot(row, doc, clr_petty)
		sum_alloc += flt(row.allocated_amount)

	if abs(sum_alloc - flt(doc.total_expense_amount)) > _EPS:
		frappe.throw(
			_("Total PM Request allocation ({0}) must equal total settlement lines amount ({1}).").format(
				sum_alloc, doc.total_expense_amount
			),
			title=_("Settlement totals"),
		)


def validate_legacy_allocation_rows(doc: Document, legacy_rows: list[Document]) -> None:
	if not doc.name:
		frappe.throw(_("Save the document before using legacy allocation data."))
	had_legacy_in_db = frappe.db.sql(
		"""
		select count(*) from `tabPM Clearance Request Allocation`
		where parent = %s
			and parenttype = 'PM Clearance'
			and parentfield = 'request_allocations'
			and ifnull(is_legacy_row, 0) = 1
		""",
		(doc.name,),
	)[0][0]
	if not had_legacy_in_db:
		frappe.throw(_("Legacy PM Request allocation rows are created only during data migration."), title=_("PM Request allocation"))
	if len(doc.request_allocations) != 1 or len(legacy_rows) != 1:
		frappe.throw(_("Legacy clearance must have exactly one legacy PM Request allocation row."), title=_("PM Request allocation"))
	lr = legacy_rows[0]
	if lr.pm_request:
		frappe.throw(_("Legacy allocation row must not reference a PM Request."))
	if abs(flt(lr.allocated_amount) - flt(doc.total_expense_amount)) > _EPS:
		frappe.throw(_("Legacy allocated amount must equal total settlement amount ({0}).").format(doc.total_expense_amount))
	lr.request_amount = 0.0
	lr.paid_amount = 0.0
	lr.previously_allocated_amount = 0.0
	lr.available_amount = 0.0


def validate_pm_request_matches_clearance(row: Document, doc: Document, clr_petty: str) -> None:
	req = frappe.get_doc("PM Request", row.pm_request)
	req_petty = request_petty_cash_account(req)
	if req.employee != doc.employee:
		frappe.throw(
			_("Row {0}: PM Request {1} is for employee {2}; this clearance is for employee {3}.").format(
				row.idx, row.pm_request, req.employee, doc.employee
			),
			title=_("PM Request mismatch"),
		)
	if req.company != doc.company:
		frappe.throw(
			_("Row {0}: PM Request {1} belongs to company {2}; clearance company is {3}.").format(
				row.idx, row.pm_request, req.company, doc.company
			),
			title=_("PM Request mismatch"),
		)
	if (req.holder or "") != (doc.holder or ""):
		frappe.throw(
			_("Row {0}: PM Request {1} holder {2} does not match clearance holder {3}.").format(
				row.idx, row.pm_request, req.holder or "-", doc.holder or "-"
			),
			title=_("PM Request mismatch"),
		)
	if (req_petty or "").strip() != (clr_petty or "").strip():
		frappe.throw(
			_(
				"Row {0}: PM Request {1} advances petty cash account {2}, but this clearance uses {3}. "
				"Select a PM Request for the same employee and holder."
			).format(row.idx, row.pm_request, req_petty or _("(empty)"), clr_petty or _("(empty)")),
			title=_("Petty cash account mismatch"),
		)

	ok, reason = pm_request_passes_clearance_filters(
		row.pm_request,
		employee=doc.employee,
		company=doc.company,
		holder=doc.holder or "",
		clearance_petty=clr_petty,
	)
	if not ok:
		frappe.throw(_("Row {0}: {1}").format(row.idx, reason))


def stamp_allocation_snapshot(row: Document, doc: Document, clr_petty: str) -> None:
	ctx = get_pm_request_allocation_context(
		row.pm_request,
		pm_clearance=doc.name if getattr(doc, "name", None) else None,
		company=doc.company,
		employee=doc.employee,
		holder=doc.holder or "",
		petty_cash_account=clr_petty,
	)
	row.request_amount = flt(ctx.get("request_amount"))
	row.paid_amount = flt(ctx.get("paid_amount"))
	if row.paid_amount <= 0:
		frappe.throw(
			_("Row {0}: PM Request {1} has no submitted Payment Entry. Please create/submit Payment Entry first.").format(
				row.idx, row.pm_request
			)
		)
	row.previously_allocated_amount = flt(ctx.get("previously_allocated_amount"))
	row.available_amount = flt(ctx.get("available_amount"))
	if flt(row.allocated_amount) <= 0:
		frappe.throw(_("Row {0}: Allocated Amount must be greater than zero.").format(row.idx))
	if flt(row.allocated_amount) > flt(row.available_amount) + _EPS:
		frappe.throw(
			_("Row {0}: allocated {1} exceeds available PM Request balance {2} for {3}.").format(
				row.idx, row.allocated_amount, row.available_amount, row.pm_request
			)
		)


@frappe.whitelist()
def get_pm_request_allocation_context(
	pm_request: str,
	pm_clearance: str | None = None,
	company: str | None = None,
	employee: str | None = None,
	holder: str | None = None,
	petty_cash_account: str | None = None,
) -> dict[str, Any]:
	"""Public UI API for stamping one PM Request allocation row.

	PM Clearance uses this from the grid when a PM Request is selected. Keep the
	signature aligned with ``pm_clearance.js`` and validation server-side.
	"""
	if not pm_request:
		return {}
	if not frappe.has_permission("PM Request", "read", pm_request):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	exclude_clearance = pm_clearance if pm_clearance and frappe.db.exists("PM Clearance", pm_clearance) else None
	if exclude_clearance:
		cl = frappe.get_doc("PM Clearance", pm_clearance)
		if not frappe.has_permission("PM Clearance", "read", doc=cl):
			frappe.throw(_("Not permitted"), frappe.PermissionError)
		company = cl.company
		employee = cl.employee
		holder = cl.holder or get_pm_holder_name(cl.employee, cl.company) or ""
		petty_cash_account = clearance_petty_cash_account(cl) or get_holder_petty_cash_account(holder)

	req = frappe.get_doc("PM Request", pm_request)
	req_holder = req.holder or get_pm_holder_name(req.employee, req.company) or ""
	req_petty = get_holder_petty_cash_account(req_holder)

	if company and req.company != company:
		frappe.throw(_("PM Request belongs to another company"), title=_("Invalid PM Request"))
	if employee and req.employee != employee:
		frappe.throw(_("PM Request belongs to another employee"), title=_("Invalid PM Request"))
	if holder and req_holder != holder:
		frappe.throw(_("PM Request belongs to another PM Holder"), title=_("Invalid PM Request"))
	if petty_cash_account and req_petty != (petty_cash_account or "").strip():
		frappe.throw(_("PM Request petty cash account does not match this clearance holder"), title=_("Invalid PM Request"))

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
	return {
		"pm_request": pm_request,
		"request_amount": flt(req.total_requested_amount),
		"paid_amount": paid,
		"previously_allocated_amount": prev,
		"available_amount": flt(paid) - flt(prev),
		"employee": req.employee,
		"holder": req_holder,
		"petty_cash_account": req_petty,
		"company": req.company,
	}


def pm_request_query_for_pm_clearance(doctype, txt, searchfield, start, page_len, filters):
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
	out = []
	for (name,) in rows:
		if get_pm_request_available_amount(name, filters.get("pm_clearance") or None) > _EPS:
			out.append([name])
	return out

