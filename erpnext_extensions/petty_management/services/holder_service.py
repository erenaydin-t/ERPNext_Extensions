from __future__ import annotations

from dataclasses import dataclass

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate, today

from erpnext.accounts.utils import get_balance_on

from erpnext_extensions.petty_management.utils import get_pm_holder_name


@dataclass(frozen=True)
class HolderBalances:
	account_gl_balance: float
	total_paid_amount: float
	total_allocated_amount: float
	available_amount: float
	pending_clearance_amount: float
	settled_amount: float
	remaining_limit: float | None


def get_holder(employee: str | None, company: str | None, *, required: bool = True) -> Document | None:
	holder_name = get_pm_holder_name(employee, company)
	if not holder_name:
		if required:
			frappe.throw(_("No PM Holder found for this employee and company. Please create PM Holder first."))
		return None
	return frappe.get_doc("PM Holder", holder_name)


def get_holder_petty_cash_account(holder: str | None) -> str:
	if not holder:
		return ""
	return frappe.db.get_value("PM Holder", holder, "petty_cash_account") or ""


def clearance_petty_cash_account(doc: Document) -> str:
	if getattr(doc, "petty_cash_account", None):
		return (doc.petty_cash_account or "").strip()
	if getattr(doc, "holder", None):
		return get_holder_petty_cash_account(doc.holder)
	return ""


def request_petty_cash_account(pm_request_doc: Document) -> str:
	holder_name = pm_request_doc.holder or get_pm_holder_name(pm_request_doc.employee, pm_request_doc.company)
	return get_holder_petty_cash_account(holder_name)


def validate_holder(doc: Document) -> None:
	if not doc.employee:
		frappe.throw(_("Employee is required"))
	if not doc.company:
		frappe.throw(_("Company is required"))
	if not doc.petty_cash_account:
		frappe.throw(_("Petty Cash Account is required"))

	validate_unique_employee_company(doc)
	validate_petty_cash_account_company(doc.petty_cash_account, doc.company)
	set_holder_balance_fields(doc)


def validate_unique_employee_company(doc: Document) -> None:
	filters = {"employee": doc.employee, "company": doc.company}
	if doc.name:
		filters["name"] = ["!=", doc.name]
	if frappe.db.exists("PM Holder", filters):
		frappe.throw(
			_("A PM Holder already exists for this employee and company."),
			title=_("Duplicate PM Holder"),
		)


def validate_petty_cash_account_company(account: str | None, company: str | None) -> None:
	if not account or not company:
		return
	acc_company = frappe.db.get_value("Account", account, "company")
	if acc_company and acc_company != company:
		frappe.throw(_("Petty Cash Account {0} must belong to company {1}").format(account, company))


def sync_request_holder_fields(doc: Document) -> Document:
	holder = get_holder(doc.employee, doc.company)
	doc.holder = holder.name
	doc.petty_cash_account = holder.petty_cash_account
	doc.max_balance_for_petty_cash = holder.max_balance
	balances = get_holder_balances(holder.name, posting_date=doc.transaction_date or today())
	doc.previous_balance = balances.available_amount
	return holder


def sync_clearance_holder_fields(doc: Document) -> Document:
	holder = get_holder(doc.employee, doc.company)
	doc.holder = holder.name
	doc.petty_cash_account = holder.petty_cash_account
	balances = get_holder_balances(holder.name, posting_date=doc.transaction_date or today())
	doc.pending_amount = balances.available_amount
	doc.current_petty_balance = balances.available_amount
	doc.total_funded_amount = balances.total_paid_amount
	doc.total_cleared_amount = balances.settled_amount
	return holder


def set_holder_balance_fields(holder_doc: Document) -> None:
	balances = get_holder_balances(holder_doc.name)
	holder_doc.account_gl_balance = balances.account_gl_balance
	holder_doc.current_balance = balances.available_amount
	holder_doc.pending_clearance_amount = balances.pending_clearance_amount
	holder_doc.consumed_amount = balances.settled_amount


def get_holder_balances(holder: str, posting_date=None) -> HolderBalances:
	row = frappe.db.get_value(
		"PM Holder",
		holder,
		["employee", "company", "petty_cash_account", "max_balance"],
		as_dict=True,
	)
	if not row:
		return HolderBalances(0, 0, 0, 0, 0, 0, None)

	as_on = getdate(posting_date or today())
	account_gl_balance = flt(
		get_balance_on(account=row.petty_cash_account, date=as_on, company=row.company)
	)
	total_paid = get_holder_paid_amount(holder)
	total_allocated = get_holder_allocated_amount(holder)
	pending = get_holder_pending_clearance_amount(holder)
	settled = get_holder_settled_amount(holder)
	available = total_paid - total_allocated
	remaining_limit = (flt(row.max_balance) - available) if row.max_balance is not None else None

	return HolderBalances(
		account_gl_balance=account_gl_balance,
		total_paid_amount=total_paid,
		total_allocated_amount=total_allocated,
		available_amount=available,
		pending_clearance_amount=pending,
		settled_amount=settled,
		remaining_limit=remaining_limit,
	)


def get_holder_context(employee: str | None, company: str | None, posting_date=None) -> dict:
	holder = get_holder(employee, company, required=False)
	if not holder:
		return {}
	balances = get_holder_balances(holder.name, posting_date=posting_date)
	return {
		"name": holder.name,
		"employee": holder.employee,
		"company": holder.company,
		"petty_cash_account": holder.petty_cash_account,
		"max_balance": holder.max_balance,
		"default_employee_bank_account": holder.default_employee_bank_account,
		"account_gl_balance": balances.account_gl_balance,
		"current_balance": balances.available_amount,
		"pending_clearance_amount": balances.pending_clearance_amount,
		"consumed_amount": balances.settled_amount,
		"total_funded_amount": balances.total_paid_amount,
		"total_allocated_amount": balances.total_allocated_amount,
		"remaining_limit": balances.remaining_limit,
	}


def get_holder_paid_amount(holder: str) -> float:
	if not frappe.db.has_table("PM Request"):
		return 0.0
	return flt(
		frappe.db.sql(
			"""
			select coalesce(sum(
				case
					when ifnull(pe.paid_amount, 0) > 0 then pe.paid_amount
					when ifnull(pe.received_amount, 0) > 0 then pe.received_amount
					else pr.total_requested_amount
				end
			), 0)
			from `tabPM Request` pr
			inner join `tabPayment Entry` pe on pe.name = pr.payment_entry and pe.docstatus = 1
			where pr.holder = %s
				and pr.docstatus = 1
				and ifnull(pr.payment_status, '') = 'Paid'
			""",
			holder,
		)[0][0]
	)


def get_holder_allocated_amount(holder: str) -> float:
	if not frappe.db.has_table("PM Clearance Request Allocation"):
		return 0.0
	from erpnext_extensions.petty_management.services.allocation_service import clearance_reserves_pm_request_balance_sql

	res = clearance_reserves_pm_request_balance_sql("cl")
	return flt(
		frappe.db.sql(
			f"""
			select coalesce(sum(a.allocated_amount), 0)
			from `tabPM Clearance Request Allocation` a
			inner join `tabPM Request` pr on pr.name = a.pm_request
			inner join `tabPM Clearance` cl on cl.name = a.parent and a.parenttype = 'PM Clearance'
			where pr.holder = %s
				and a.parentfield = 'request_allocations'
				and ifnull(a.is_legacy_row, 0) = 0
				and {res}
			""",
			holder,
		)[0][0]
	)


def get_holder_pending_clearance_amount(holder: str) -> float:
	if not frappe.db.has_table("PM Clearance"):
		return 0.0
	return flt(
		frappe.db.sql(
			"""
			select coalesce(sum(cl.total_expense_amount), 0)
			from `tabPM Clearance` cl
			where cl.holder = %s
				and cl.docstatus = 1
				and ifnull(cl.status, '') not in ('Cancelled', 'Rejected')
				and (
					ifnull(cl.journal_entry, '') = ''
					or ifnull((
						select je.docstatus from `tabJournal Entry` je
						where je.name = cl.journal_entry limit 1
					), 0) != 1
				)
			""",
			holder,
		)[0][0]
	)


def get_holder_settled_amount(holder: str) -> float:
	"""Amount cleared in accounting: submitted clearance + submitted settlement JE only."""
	if not frappe.db.has_table("PM Clearance"):
		return 0.0
	return flt(
		frappe.db.sql(
			"""
			select coalesce(sum(cl.total_expense_amount), 0)
			from `tabPM Clearance` cl
			inner join `tabJournal Entry` je on je.name = cl.journal_entry and je.docstatus = 1
			where cl.holder = %s
				and cl.docstatus = 1
				and ifnull(cl.status, '') not in ('Cancelled', 'Rejected')
			""",
			holder,
		)[0][0]
	)

