"""Reconciliation and integrity checks for Petty Management (operational + accounting).

Scans for broken references, mixed states, and amount inconsistencies. Optional
``apply_safe_fixes`` only performs non-GL metadata repairs (e.g. clear stale links
when the target document is already cancelled / missing).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import frappe
from frappe import _
from frappe.utils import cint, flt

from erpnext_extensions.petty_management.services.allocation_service import (
	clearance_reserves_pm_request_balance_sql,
	get_pm_request_paid_amount,
)
from erpnext_extensions.petty_management.services.holder_service import get_holder_balances


@dataclass
class ReconciliationIssue:
	severity: str  # "error" | "warning"
	code: str
	title: str
	detail: str
	references: dict[str, Any] = field(default_factory=dict)
	suggested_fix: str | None = None


@dataclass
class ReconciliationResult:
	issues: list[ReconciliationIssue] = field(default_factory=list)
	fixes_applied: list[str] = field(default_factory=list)

	def to_dict(self) -> dict[str, Any]:
		return {
			"issues": [asdict(i) for i in self.issues],
			"fixes_applied": list(self.fixes_applied),
			"summary": {
				"errors": sum(1 for i in self.issues if i.severity == "error"),
				"warnings": sum(1 for i in self.issues if i.severity == "warning"),
			},
		}


def reconcile(*, apply_safe_fixes: bool = False, company: str | None = None) -> ReconciliationResult:
	"""Run all integrity checks. When ``apply_safe_fixes`` and user is System Manager, apply safe metadata repairs."""
	res = ReconciliationResult()
	_check_pm_request_pe_semantics(res, company=company, fix=apply_safe_fixes)
	_check_pm_clearance_je_semantics(res, company=company, fix=apply_safe_fixes)
	_check_duplicate_pe_reference(res, company=company)
	_check_duplicate_je_clearance_link(res, company=company)
	_check_reserved_vs_funded(res, company=company)
	_check_holder_available_negative(res, company=company)
	_check_clearance_status_vs_je(res, company=company)
	return res


def _check_pm_request_pe_semantics(
	res: ReconciliationResult, *, company: str | None, fix: bool
) -> None:
	filters = {}
	if company:
		filters["company"] = company
	for pr in frappe.get_all("PM Request", filters=filters or None, pluck="name"):
		row = frappe.db.get_value(
			"PM Request",
			pr,
			["payment_entry", "payment_status", "docstatus", "employee", "holder"],
			as_dict=True,
		)
		if not row:
			continue
		ps = (row.payment_status or "").strip()
		pe = row.payment_entry
		if ps == "Paid":
			if not pe:
				res.issues.append(
					ReconciliationIssue(
						severity="error",
						code="PR_PAID_NO_PE",
						title=_("PM Request marked Paid without Payment Entry"),
						detail=pr,
						references={"pm_request": pr},
						suggested_fix=_("Run validate on PM Request or clear payment_status."),
					)
				)
				continue
			if not frappe.db.exists("Payment Entry", pe):
				res.issues.append(
					ReconciliationIssue(
						severity="error",
						code="PR_PE_MISSING",
						title=_("Payment Entry link points to missing document"),
						detail=f"{pr} → {pe}",
						references={"pm_request": pr, "payment_entry": pe},
						suggested_fix=_("Clear payment_entry or restore Payment Entry."),
					)
				)
				if fix and _can_fix():
					frappe.db.set_value(
						"PM Request",
						pr,
						{"payment_entry": None, "payment_status": "Not Paid"},
						update_modified=False,
					)
					res.fixes_applied.append(f"Cleared stale payment_entry on {pr}")
				continue
			pds = cint(frappe.db.get_value("Payment Entry", pe, "docstatus"))
			if pds != 1:
				res.issues.append(
					ReconciliationIssue(
						severity="error",
						code="PR_PAID_PE_NOT_SUBMITTED",
						title=_("PM Request Paid but Payment Entry not submitted"),
						detail=f"{pr} PE {pe} docstatus={pds}",
						references={"pm_request": pr, "payment_entry": pe},
					)
				)
		if pe and frappe.db.exists("Payment Entry", pe):
			pds = cint(frappe.db.get_value("Payment Entry", pe, "docstatus"))
			if pds == 2 and ps == "Paid":
				res.issues.append(
					ReconciliationIssue(
						severity="warning",
						code="PR_PAID_PE_CANCELLED",
						title=_("Payment Entry cancelled but PM Request still Paid"),
						detail=pr,
						references={"pm_request": pr, "payment_entry": pe},
					)
				)
				if fix and _can_fix():
					frappe.db.set_value(
						"PM Request",
						pr,
						{"payment_entry": None, "payment_status": "Not Paid"},
						update_modified=False,
					)
					res.fixes_applied.append(f"Reset funding fields on {pr} after cancelled PE")


def _check_pm_clearance_je_semantics(
	res: ReconciliationResult, *, company: str | None, fix: bool
) -> None:
	filters = {}
	if company:
		filters["company"] = company
	for cl_name in frappe.get_all("PM Clearance", filters=filters or None, pluck="name"):
		row = frappe.db.get_value(
			"PM Clearance",
			cl_name,
			["journal_entry", "status", "docstatus", "holder", "employee"],
			as_dict=True,
		)
		if not row:
			continue
		st = (row.status or "").strip()
		je = row.journal_entry
		if st == "Settled":
			if not je:
				res.issues.append(
					ReconciliationIssue(
						severity="error",
						code="CL_SETTLED_NO_JE",
						title=_("PM Clearance Settled without Journal Entry"),
						detail=cl_name,
						references={"pm_clearance": cl_name},
					)
				)
			elif frappe.db.exists("Journal Entry", je):
				jds = cint(frappe.db.get_value("Journal Entry", je, "docstatus"))
				if jds != 1:
					res.issues.append(
						ReconciliationIssue(
							severity="error",
							code="CL_SETTLED_JE_NOT_SUBMITTED",
							title=_("PM Clearance Settled but Journal Entry not submitted"),
							detail=f"{cl_name} JE {je} docstatus={jds}",
							references={"pm_clearance": cl_name, "journal_entry": je},
						)
					)
		if je:
			if not frappe.db.exists("Journal Entry", je):
				res.issues.append(
					ReconciliationIssue(
						severity="warning",
						code="CL_JE_MISSING",
						title=_("Journal Entry link missing"),
						detail=f"{cl_name} → {je}",
						references={"pm_clearance": cl_name, "journal_entry": je},
					)
				)
				if fix and _can_fix():
					frappe.db.set_value("PM Clearance", cl_name, {"journal_entry": None}, update_modified=False)
					res.fixes_applied.append(f"Cleared missing journal_entry on {cl_name}")
			else:
				jds = cint(frappe.db.get_value("Journal Entry", je, "docstatus"))
				if jds == 2 and st == "Settled":
					res.issues.append(
						ReconciliationIssue(
							severity="warning",
							code="CL_SETTLED_JE_CANCELLED",
							title=_("Settlement Journal Entry cancelled but clearance still Settled"),
							detail=cl_name,
							references={"pm_clearance": cl_name, "journal_entry": je},
						)
					)


def _check_duplicate_je_clearance_link(res: ReconciliationResult, *, company: str | None) -> None:
	"""Multiple Journal Entries referencing the same PM Clearance (custom link if present)."""
	meta = frappe.get_meta("Journal Entry")
	if not meta.has_field("custom_pm_clearance"):
		return
	co_sql = " AND je.company = %(company)s " if company else ""
	rows = frappe.db.sql(
		f"""
		select je.custom_pm_clearance as pm_clearance, count(*) as c
		from `tabJournal Entry` je
		where ifnull(je.custom_pm_clearance, '') != ''
			and je.docstatus in (0, 1)
			{co_sql}
		group by je.custom_pm_clearance
		having count(*) > 1
		""",
		{"company": company} if company else {},
	)
	for pm_clearance, cnt in rows:
		res.issues.append(
			ReconciliationIssue(
				severity="error",
				code="DUP_JE_PM_CLEARANCE",
				title=_("Multiple active Journal Entries reference the same PM Clearance"),
				detail=f"{pm_clearance} ({cnt})",
				references={"pm_clearance": pm_clearance},
			)
		)


def _check_duplicate_pe_reference(res: ReconciliationResult, *, company: str | None) -> None:
	"""Multiple active PE rows referencing same PM Request name (reference_no)."""
	company_sql = " AND pe.company = %(company)s " if company else ""
	rows = frappe.db.sql(
		f"""
		select pe.reference_no as pm_request, count(*) as c
		from `tabPayment Entry` pe
		where pe.docstatus in (0, 1)
			and ifnull(pe.reference_no,'') != ''
			{company_sql}
		group by pe.reference_no
		having count(*) > 1
		""",
		{"company": company} if company else {},
	)
	for pm_request, cnt in rows:
		res.issues.append(
			ReconciliationIssue(
				severity="error",
				code="DUP_PE_REFERENCE",
				title=_("Multiple active Payment Entries share reference_no"),
				detail=f"{pm_request} ({cnt})",
				references={"pm_request": pm_request},
			)
		)


def _check_reserved_vs_funded(res: ReconciliationResult, *, company: str | None) -> None:
	"""Reserved allocations on workflow-approved clearances vs funded amount per PM Request."""
	params: dict[str, Any] = {}
	co_sql = " AND pr.company = %(company)s " if company else ""
	if company:
		params["company"] = company
	res_clause = clearance_reserves_pm_request_balance_sql("cl")
	rows = frappe.db.sql(
		f"""
		select
			a.pm_request,
			sum(a.allocated_amount) as reserved
		from `tabPM Clearance Request Allocation` a
		inner join `tabPM Clearance` cl on cl.name = a.parent and a.parenttype = 'PM Clearance'
		inner join `tabPM Request` pr on pr.name = a.pm_request
		where a.parentfield = 'request_allocations'
			and ifnull(a.is_legacy_row, 0) = 0
			and {res_clause}
			{co_sql}
		group by a.pm_request
		""",
		params,
		as_dict=True,
	)
	for row in rows:
		pm_request = row.pm_request
		reserved = flt(row.reserved)
		funded = flt(get_pm_request_paid_amount(pm_request))
		if funded + 1e-6 < reserved:
			res.issues.append(
				ReconciliationIssue(
					severity="error",
					code="RESERVED_EXCEEDS_FUNDED",
					title=_("Reserved clearance allocations exceed funded PM Request amount"),
					detail=f"{pm_request} reserved={reserved} funded={funded}",
					references={"pm_request": pm_request},
				)
			)


def _check_holder_available_negative(res: ReconciliationResult, *, company: str | None) -> None:
	"""Holder available = funded - reserved; flag unexpected negatives when settings disallow."""
	from erpnext_extensions.petty_management.utils import get_pm_settings

	settings = get_pm_settings()
	if settings and settings.allow_negative_balance:
		return
	filters: dict[str, Any] = {}
	if company:
		filters["company"] = company
	for holder in frappe.get_all("PM Holder", filters=filters or None, pluck="name"):
		b = get_holder_balances(holder)
		if b.available_amount < -1e-3:
			res.issues.append(
				ReconciliationIssue(
					severity="warning",
					code="HOLDER_AVAILABLE_NEGATIVE",
					title=_("Holder available balance is negative"),
					detail=f"{holder} available={b.available_amount}",
					references={"holder": holder},
				)
			)


def _check_clearance_status_vs_je(res: ReconciliationResult, *, company: str | None) -> None:
	"""Clearance says Pending JE Submission but no draft JE, etc."""
	co_sql = " AND cl.company = %(company)s " if company else ""
	params: dict[str, Any] = {}
	if company:
		params["company"] = company
	rows = frappe.db.sql(
		f"""
		select cl.name, cl.status, cl.journal_entry,
			ifnull(je.docstatus, -1) as je_ds
		from `tabPM Clearance` cl
		left join `tabJournal Entry` je on je.name = cl.journal_entry
		where cl.docstatus = 1
			and cl.status = 'Pending Journal Entry Submission'
			{co_sql}
		""",
		params,
		as_dict=True,
	)
	for row in rows:
		if not row.journal_entry:
			res.issues.append(
				ReconciliationIssue(
					severity="warning",
					code="CL_PENDING_JE_BUT_NO_LINK",
					title=_("Status Pending JE Submission but journal_entry empty"),
					detail=row.name,
					references={"pm_clearance": row.name},
				)
			)


def _can_fix() -> bool:
	return bool(frappe.session and ("System Manager" in frappe.get_roles()))


@frappe.whitelist()
def run_pm_reconciliation_api(company: str | None = None, apply_safe_fixes: int | bool = 0) -> dict[str, Any]:
	"""System Managers only: run reconciliation; optional safe metadata fixes."""
	frappe.only_for("System Manager")
	fix = bool(int(apply_safe_fixes)) if apply_safe_fixes is not True else apply_safe_fixes
	result = reconcile(apply_safe_fixes=fix, company=company or None)
	out = result.to_dict()
	if out.get("summary", {}).get("errors"):
		try:
			from erpnext_extensions.petty_management import petty_audit

			petty_audit.log_event(
				"pm_reconciliation_errors",
				company=company,
				summary=out.get("summary"),
				issue_codes=[i.get("code") for i in out.get("issues", []) if i.get("severity") == "error"],
			)
		except Exception:
			pass
	return out
