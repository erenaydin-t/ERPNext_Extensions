from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt, getdate, today

from erpnext_extensions.petty_management.services.allocation_service import (
	get_pm_request_available_amount,
	get_pm_request_paid_amount,
	sum_prior_pm_request_allocations,
)
from erpnext_extensions.petty_management.services.holder_service import get_holder_balances


def get_holder_rows(filters=None):
	filters = frappe._dict(filters or {})
	conditions = "1=1"
	params: dict = {}
	if filters.get("company"):
		conditions += " and company = %(company)s"
		params["company"] = filters.company
	if filters.get("employee"):
		conditions += " and employee = %(employee)s"
		params["employee"] = filters.employee

	return frappe.db.sql(
		f"""
		select name, employee, employee_name, company, petty_cash_account, max_balance
		from `tabPM Holder`
		where {conditions}
		order by company, employee
		""",
		params,
		as_dict=True,
	)


def get_pm_balance_report_data(filters=None):
	columns = [
		{"label": _("Employee"), "fieldname": "employee", "fieldtype": "Link", "options": "Employee", "width": 140},
		{"label": _("Employee Name"), "fieldname": "employee_name", "fieldtype": "Data", "width": 160},
		{"label": _("Company"), "fieldname": "company", "fieldtype": "Link", "options": "Company", "width": 140},
		{"label": _("Petty Cash Account"), "fieldname": "petty_cash_account", "fieldtype": "Link", "options": "Account", "width": 160},
		{"label": _("Funded Balance"), "fieldname": "funded_available_amount", "fieldtype": "Currency", "width": 130},
		{"label": _("Opening Balance"), "fieldname": "opening_available_amount", "fieldtype": "Currency", "width": 130},
		{"label": _("Total Available"), "fieldname": "current_balance", "fieldtype": "Currency", "width": 130},
		{"label": _("Account GL Balance"), "fieldname": "account_gl_balance", "fieldtype": "Currency", "width": 130},
		{"label": _("Total Funded (Paid)"), "fieldname": "total_paid_amount", "fieldtype": "Currency", "width": 120},
		{"label": _("Funded Reserved"), "fieldname": "funded_reserved_amount", "fieldtype": "Currency", "width": 120},
		{"label": _("Opening Gross"), "fieldname": "opening_gross_amount", "fieldtype": "Currency", "width": 120},
		{"label": _("Opening Previously Settled"), "fieldname": "opening_previously_settled_amount", "fieldtype": "Currency", "width": 150},
		{"label": _("Opening Remaining at Cutover"), "fieldname": "opening_remaining_at_cutover", "fieldtype": "Currency", "width": 160},
		{"label": _("Opening Allocated in PM"), "fieldname": "opening_allocated_amount", "fieldtype": "Currency", "width": 150},
		{"label": _("Pending Settlement Amount"), "fieldname": "pending_clearance_amount", "fieldtype": "Currency", "width": 140},
		{"label": _("Settled Amount"), "fieldname": "consumed_amount", "fieldtype": "Currency", "width": 120},
		{"label": _("Max Balance"), "fieldname": "max_balance", "fieldtype": "Currency", "width": 120},
		{"label": _("Remaining Limit"), "fieldname": "remaining_limit", "fieldtype": "Currency", "width": 120},
	]

	data = []
	for holder in get_holder_rows(filters):
		balances = get_holder_balances(holder.name)
		from erpnext_extensions.petty_management.services.holder_service import get_holder_funded_reserved_amount

		data.append(
			{
				**holder,
				"account_gl_balance": balances.account_gl_balance,
				"funded_available_amount": balances.funded_available_amount,
				"opening_available_amount": balances.opening_available_amount,
				"current_balance": balances.available_amount,
				"total_paid_amount": balances.total_paid_amount,
				"total_allocated_amount": balances.total_allocated_amount,
				"funded_reserved_amount": get_holder_funded_reserved_amount(holder.name),
				"opening_gross_amount": balances.opening_gross_amount,
				"opening_previously_settled_amount": balances.opening_previously_settled_amount,
				"opening_remaining_at_cutover": balances.opening_remaining_at_cutover,
				"opening_allocated_amount": balances.opening_allocated_amount,
				"pending_clearance_amount": balances.pending_clearance_amount,
				"consumed_amount": balances.settled_amount,
				"remaining_limit": balances.remaining_limit,
			}
		)
	return columns, data


def get_pm_opening_advance_availability_report_data(filters=None):
	filters = frappe._dict(filters or {})
	columns = [
		{
			"label": _("PM Opening Advance"),
			"fieldname": "pm_opening_advance",
			"fieldtype": "Link",
			"options": "PM Opening Advance",
			"width": 170,
		},
		{"label": _("Opening Source Type"), "fieldname": "opening_source_type", "fieldtype": "Data", "width": 140},
		{"label": _("Reference No"), "fieldname": "reference_no", "fieldtype": "Data", "width": 120},
		{"label": _("Holder"), "fieldname": "holder", "fieldtype": "Link", "options": "PM Holder", "width": 150},
		{"label": _("Employee"), "fieldname": "employee", "fieldtype": "Link", "options": "Employee", "width": 130},
		{"label": _("Company"), "fieldname": "company", "fieldtype": "Link", "options": "Company", "width": 130},
		{"label": _("Petty Cash Account"), "fieldname": "petty_cash_account", "fieldtype": "Link", "options": "Account", "width": 160},
		{"label": _("Opening Advance"), "fieldname": "opening_advance_amount", "fieldtype": "Currency", "width": 130},
		{
			"label": _("Previously Settled Before Migration"),
			"fieldname": "previously_settled_before_migration",
			"fieldtype": "Currency",
			"width": 180,
		},
		{"label": _("Remaining at Cutover"), "fieldname": "remaining_at_cutover", "fieldtype": "Currency", "width": 140},
		{"label": _("Allocated in PM"), "fieldname": "allocated_in_pm", "fieldtype": "Currency", "width": 130},
		{"label": _("Available Opening Balance"), "fieldname": "available_opening_balance", "fieldtype": "Currency", "width": 160},
		{"label": _("Opening Date"), "fieldname": "opening_date", "fieldtype": "Date", "width": 110},
	]
	conditions = ["oa.docstatus = 1", "ifnull(oa.status, '') = 'Submitted'"]
	params: dict = {}
	if filters.get("company"):
		conditions.append("oa.company = %(company)s")
		params["company"] = filters.company
	if filters.get("employee"):
		conditions.append("oa.employee = %(employee)s")
		params["employee"] = filters.employee
	if filters.get("holder"):
		conditions.append("oa.holder = %(holder)s")
		params["holder"] = filters.holder

	from erpnext_extensions.petty_management.services.opening_advance_service import (
		compute_opening_advance_derived_fields,
	)

	rows = frappe.db.sql(
		f"""
		select
			oa.name as pm_opening_advance,
			oa.opening_source_type,
			oa.reference_no,
			oa.holder,
			oa.employee,
			oa.company,
			oa.petty_cash_account,
			oa.opening_advance_amount,
			oa.previously_settled_before_migration,
			oa.opening_date
		from `tabPM Opening Advance` oa
		where {" and ".join(conditions)}
		order by oa.opening_date, oa.name
		""",
		params,
		as_dict=True,
	)
	data = []
	for row in rows:
		derived = compute_opening_advance_derived_fields(row.pm_opening_advance)
		row["remaining_at_cutover"] = derived["remaining_at_cutover"]
		row["allocated_in_pm"] = derived["allocated_in_pm"]
		row["available_opening_balance"] = derived["available_opening_balance"]
		if filters.get("only_available") and flt(row["available_opening_balance"]) <= 0:
			continue
		data.append(row)
	return columns, data


def get_pm_pending_clearance_report_data(filters=None):
	columns = [
		{"label": _("Employee"), "fieldname": "employee", "fieldtype": "Link", "options": "Employee", "width": 140},
		{"label": _("Employee Name"), "fieldname": "employee_name", "fieldtype": "Data", "width": 160},
		{"label": _("Company"), "fieldname": "company", "fieldtype": "Link", "options": "Company", "width": 140},
		{"label": _("Petty Cash Account"), "fieldname": "petty_cash_account", "fieldtype": "Link", "options": "Account", "width": 160},
		{"label": _("Account GL Balance"), "fieldname": "account_gl_balance", "fieldtype": "Currency", "width": 130},
		{"label": _("Holder Available Amount"), "fieldname": "current_balance", "fieldtype": "Currency", "width": 130},
		{"label": _("Pending Settlement Amount"), "fieldname": "pending_clearance_amount", "fieldtype": "Currency", "width": 140},
		{"label": _("Last Clearance Date"), "fieldname": "last_clearance_date", "fieldtype": "Date", "width": 140},
	]

	data = []
	for holder in get_holder_rows(filters):
		balances = get_holder_balances(holder.name)
		if balances.available_amount <= 0 and balances.pending_clearance_amount <= 0:
			continue
		last_dt = frappe.db.sql(
			"""
			select max(transaction_date) from `tabPM Clearance`
			where holder=%s and docstatus=1
			""",
			holder.name,
		)[0][0]
		data.append(
			{
				**holder,
				"account_gl_balance": balances.account_gl_balance,
				"current_balance": balances.available_amount,
				"pending_clearance_amount": balances.pending_clearance_amount,
				"last_clearance_date": last_dt,
			}
		)
	return columns, data


def get_pm_request_availability_report_data(filters=None):
	filters = frappe._dict(filters or {})
	columns = [
		{"label": _("PM Request"), "fieldname": "pm_request", "fieldtype": "Link", "options": "PM Request", "width": 170},
		{"label": _("Employee"), "fieldname": "employee", "fieldtype": "Link", "options": "Employee", "width": 140},
		{"label": _("Holder"), "fieldname": "holder", "fieldtype": "Link", "options": "PM Holder", "width": 160},
		{"label": _("Company"), "fieldname": "company", "fieldtype": "Link", "options": "Company", "width": 140},
		{"label": _("Petty Cash Account"), "fieldname": "petty_cash_account", "fieldtype": "Link", "options": "Account", "width": 170},
		{"label": _("Payment Entry"), "fieldname": "payment_entry", "fieldtype": "Link", "options": "Payment Entry", "width": 160},
		{"label": _("Request Amount"), "fieldname": "request_amount", "fieldtype": "Currency", "width": 130},
		{"label": _("Paid Amount"), "fieldname": "paid_amount", "fieldtype": "Currency", "width": 130},
		{"label": _("Reserved / Allocated"), "fieldname": "allocated_amount", "fieldtype": "Currency", "width": 140},
		{"label": _("Available Amount"), "fieldname": "available_amount", "fieldtype": "Currency", "width": 140},
		{"label": _("Posting Date"), "fieldname": "posting_date", "fieldtype": "Date", "width": 110},
	]

	conditions = ["pr.docstatus = 1", "ifnull(pr.payment_status, '') = 'Paid'"]
	params = {}
	if filters.get("company"):
		conditions.append("pr.company = %(company)s")
		params["company"] = filters.company
	if filters.get("employee"):
		conditions.append("pr.employee = %(employee)s")
		params["employee"] = filters.employee
	if filters.get("holder"):
		conditions.append("pr.holder = %(holder)s")
		params["holder"] = filters.holder
	if filters.get("from_date"):
		conditions.append("pr.transaction_date >= %(from_date)s")
		params["from_date"] = filters.from_date
	if filters.get("to_date"):
		conditions.append("pr.transaction_date <= %(to_date)s")
		params["to_date"] = filters.to_date

	rows = frappe.db.sql(
		f"""
		select
			pr.name as pm_request,
			pr.employee,
			pr.holder,
			pr.company,
			h.petty_cash_account,
			pr.payment_entry,
			pr.total_requested_amount as request_amount,
			pr.transaction_date as posting_date
		from `tabPM Request` pr
		left join `tabPM Holder` h on h.name = pr.holder
		where {" and ".join(conditions)}
		order by pr.transaction_date, pr.name
		""",
		params,
		as_dict=True,
	)
	data = []
	for row in rows:
		paid = get_pm_request_paid_amount(row.pm_request)
		allocated = sum_prior_pm_request_allocations(row.pm_request, None)
		available = get_pm_request_available_amount(row.pm_request)
		if filters.get("only_available") and available <= 0:
			continue
		data.append({**row, "paid_amount": paid, "allocated_amount": allocated, "available_amount": available})
	return columns, data


def get_pm_ledger_report_data(filters=None):
	filters = frappe._dict(filters or {})
	if not filters.get("company"):
		frappe.throw(_("Company is required"))

	columns = [
		{"label": _("Date"), "fieldname": "posting_date", "fieldtype": "Date", "width": 100},
		{"label": _("Document Type"), "fieldname": "voucher_type", "fieldtype": "Data", "width": 120},
		{"label": _("Document No"), "fieldname": "voucher_no", "fieldtype": "Dynamic Link", "options": "voucher_type", "width": 140},
		{"label": _("Debit"), "fieldname": "debit", "fieldtype": "Currency", "width": 100},
		{"label": _("Credit"), "fieldname": "credit", "fieldtype": "Currency", "width": 100},
		{"label": _("Balance"), "fieldname": "balance", "fieldtype": "Currency", "width": 120},
		{"label": _("Project"), "fieldname": "project", "fieldtype": "Link", "options": "Project", "width": 140},
		{"label": _("Remarks"), "fieldname": "remarks", "fieldtype": "Data", "width": 200},
	]

	holder_filters = {"company": filters.company}
	if filters.get("employee"):
		holder_filters["employee"] = filters.employee
	accounts = frappe.get_all("PM Holder", filters=holder_filters, pluck="petty_cash_account", distinct=True)
	accounts = [a for a in accounts if a]
	if not accounts:
		return columns, []

	from_date = getdate(filters.get("from_date") or "2000-01-01")
	to_date = getdate(filters.get("to_date") or today())
	opening = 0.0
	for account in accounts:
		opening += flt(
			frappe.db.sql(
				"""
				select sum(debit) - sum(credit)
				from `tabGL Entry`
				where account = %s and company = %s and posting_date < %s
				""",
				(account, filters.company, from_date),
			)[0][0]
			or 0
		)

	rows = frappe.db.sql(
		"""
		select posting_date, voucher_type, voucher_no, debit, credit, project, remarks
		from `tabGL Entry`
		where company = %(company)s
			and account in %(accounts)s
			and posting_date between %(from_date)s and %(to_date)s
			and is_cancelled = 0
		order by posting_date, creation, name
		""",
		{
			"company": filters.company,
			"accounts": tuple(accounts),
			"from_date": from_date,
			"to_date": to_date,
		},
		as_dict=True,
	)

	balance = opening
	data = []
	if opening:
		data.append(
			{
				"posting_date": from_date,
				"voucher_type": "",
				"voucher_no": _("Opening"),
				"debit": opening if opening > 0 else 0,
				"credit": -opening if opening < 0 else 0,
				"balance": balance,
				"project": "",
				"remarks": "",
			}
		)
	for row in rows:
		balance += flt(row.debit) - flt(row.credit)
		row["balance"] = balance
		data.append(row)
	return columns, data

