# Copyright (c) 2026, Farbod Siyahpoosh and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe import _


def execute(filters=None):
	filters = frappe._dict(filters or {})
	columns = get_columns()
	data = get_settlement_rows(filters)
	data.extend(get_funding_rows(filters))
	row_type_order = {"Settlement Line": 0, "Funding Allocation Line": 1}
	data.sort(
		key=lambda row: (
			row.get("posting_date") or "",
			row.get("pm_clearance") or "",
			row_type_order.get(row.get("row_type"), 99),
		)
	)
	return columns, data


def get_columns():
	return [
		{"label": _("Row Type"), "fieldname": "row_type", "fieldtype": "Data", "width": 150},
		{"label": _("PM Clearance"), "fieldname": "pm_clearance", "fieldtype": "Link", "options": "PM Clearance", "width": 160},
		{"label": _("Clearance Status"), "fieldname": "clearance_status", "fieldtype": "Data", "width": 130},
		{"label": _("Journal Entry"), "fieldname": "journal_entry", "fieldtype": "Link", "options": "Journal Entry", "width": 160},
		{"label": _("JE Status"), "fieldname": "je_status", "fieldtype": "Data", "width": 110},
		{"label": _("Holder"), "fieldname": "holder", "fieldtype": "Link", "options": "PM Holder", "width": 150},
		{"label": _("Employee"), "fieldname": "employee", "fieldtype": "Link", "options": "Employee", "width": 140},
		{"label": _("Company"), "fieldname": "company", "fieldtype": "Link", "options": "Company", "width": 140},
		{"label": _("Petty Cash Account"), "fieldname": "petty_cash_account", "fieldtype": "Link", "options": "Account", "width": 180},
		{"label": _("Settlement Type"), "fieldname": "settlement_type", "fieldtype": "Data", "width": 140},
		{"label": _("Purchase Invoice"), "fieldname": "purchase_invoice", "fieldtype": "Link", "options": "Purchase Invoice", "width": 160},
		{"label": _("Purchase Order"), "fieldname": "purchase_order", "fieldtype": "Link", "options": "Purchase Order", "width": 160},
		{"label": _("Supplier"), "fieldname": "supplier", "fieldtype": "Link", "options": "Supplier", "width": 160},
		{"label": _("Settlement Amount"), "fieldname": "settlement_amount", "fieldtype": "Currency", "width": 140},
		{"label": _("PM Request"), "fieldname": "pm_request", "fieldtype": "Link", "options": "PM Request", "width": 160},
		{"label": _("PM Request Allocated Amount"), "fieldname": "pm_request_allocated_amount", "fieldtype": "Currency", "width": 180},
		{"label": _("Payment Entry"), "fieldname": "payment_entry", "fieldtype": "Link", "options": "Payment Entry", "width": 160},
		{"label": _("PI Outstanding Amount"), "fieldname": "pi_outstanding_amount", "fieldtype": "Currency", "width": 160},
		{"label": _("Posting Date"), "fieldname": "posting_date", "fieldtype": "Date", "width": 110},
	]


def get_conditions(filters):
	conditions = []
	params = {}

	if filters.get("company"):
		conditions.append("cl.company = %(company)s")
		params["company"] = filters.company
	if filters.get("employee"):
		conditions.append("cl.employee = %(employee)s")
		params["employee"] = filters.employee
	if filters.get("holder"):
		conditions.append("cl.holder = %(holder)s")
		params["holder"] = filters.holder
	if filters.get("pm_clearance"):
		conditions.append("cl.name = %(pm_clearance)s")
		params["pm_clearance"] = filters.pm_clearance
	if filters.get("from_date"):
		conditions.append("coalesce(je.posting_date, cl.je_clearance_date, cl.transaction_date) >= %(from_date)s")
		params["from_date"] = filters.from_date
	if filters.get("to_date"):
		conditions.append("coalesce(je.posting_date, cl.je_clearance_date, cl.transaction_date) <= %(to_date)s")
		params["to_date"] = filters.to_date

	return (" and " + " and ".join(conditions)) if conditions else "", params


def get_settlement_rows(filters):
	conditions, params = get_conditions(filters)
	rows = frappe.db.sql(
		f"""
		select
			'Settlement Line' as row_type,
			cl.name as pm_clearance,
			cl.status as clearance_status,
			cl.journal_entry,
			je.docstatus as je_docstatus,
			cl.holder,
			cl.employee,
			cl.company,
			cl.petty_cash_account,
			coalesce(nullif(d.settlement_type, ''), 'Purchase Invoice') as settlement_type,
			d.purchase_invoice,
			d.purchase_order,
			coalesce(d.supplier, pi.supplier, po.supplier) as supplier,
			d.allocated_amount as settlement_amount,
			null as pm_request,
			null as pm_request_allocated_amount,
			null as payment_entry,
			coalesce(d.outstanding_amount, pi.outstanding_amount) as pi_outstanding_amount,
			coalesce(je.posting_date, cl.je_clearance_date, cl.transaction_date) as posting_date
		from `tabPM Clearance` cl
		inner join `tabPM Clearance Detail` d
			on d.parent = cl.name
			and d.parenttype = 'PM Clearance'
			and d.parentfield = 'details'
		left join `tabJournal Entry` je on je.name = cl.journal_entry
		left join `tabPurchase Invoice` pi on pi.name = d.purchase_invoice
		left join `tabPurchase Order` po on po.name = d.purchase_order
		where 1=1 {conditions}
			and cl.docstatus = 1
		order by posting_date, cl.name, d.idx
		""",
		params,
		as_dict=True,
	)
	for row in rows:
		row["je_status"] = get_docstatus_label(row.pop("je_docstatus", None), row.get("journal_entry"))
	return rows


def get_funding_rows(filters):
	conditions, params = get_conditions(filters)
	rows = frappe.db.sql(
		f"""
		select
			'Funding Allocation Line' as row_type,
			cl.name as pm_clearance,
			cl.status as clearance_status,
			cl.journal_entry,
			je.docstatus as je_docstatus,
			cl.holder,
			cl.employee,
			cl.company,
			cl.petty_cash_account,
			null as settlement_type,
			null as purchase_invoice,
			null as purchase_order,
			null as supplier,
			null as settlement_amount,
			a.pm_request,
			a.allocated_amount as pm_request_allocated_amount,
			pr.payment_entry,
			null as pi_outstanding_amount,
			coalesce(je.posting_date, cl.je_clearance_date, cl.transaction_date) as posting_date
		from `tabPM Clearance` cl
		inner join `tabPM Clearance Request Allocation` a
			on a.parent = cl.name
			and a.parenttype = 'PM Clearance'
			and a.parentfield = 'request_allocations'
			and ifnull(a.is_legacy_row, 0) = 0
		left join `tabPM Request` pr on pr.name = a.pm_request
		left join `tabJournal Entry` je on je.name = cl.journal_entry
		where 1=1 {conditions}
			and cl.docstatus = 1
		order by posting_date, cl.name, a.idx
		""",
		params,
		as_dict=True,
	)
	for row in rows:
		row["je_status"] = get_docstatus_label(row.pop("je_docstatus", None), row.get("journal_entry"))
	return rows


def get_docstatus_label(docstatus, document_name: str | None):
	if not document_name:
		return ""
	if docstatus == 0:
		return _("Draft")
	if docstatus == 1:
		return _("Submitted")
	if docstatus == 2:
		return _("Cancelled")
	return ""

