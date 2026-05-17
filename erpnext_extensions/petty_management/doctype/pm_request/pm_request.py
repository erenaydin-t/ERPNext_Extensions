# Copyright (c) 2026, Farbod Siyahpoosh and contributors
# For license information, please see license.txt

import json

import frappe
from frappe import _
from frappe.desk.reportview import get_match_cond
from frappe.model.document import Document
from frappe.model.naming import getseries
from frappe.utils import getdate, today

from erpnext_extensions.petty_management.services.holder_service import get_holder_context
from erpnext_extensions.petty_management.services.request_service import (
	create_payment_entry as create_payment_entry_service,
	get_pm_request_action_flags as get_pm_request_action_flags_service,
	validate_request,
	validate_request_cancel,
)


class PMRequest(Document):
	"""Funds petty cash via Payment Entry; ties to PM Clearance only through PM Holder / same Petty Cash Account."""

	def autoname(self):
		if not self.employee:
			frappe.throw(_("Employee is required before naming"))
		d = getdate(self.transaction_date or today())
		emp_key = str(self.employee).replace(" ", "")[:40]
		prefix = f"REQ-{emp_key}-{d.year}-{d.month:02d}-"
		self.name = prefix + getseries(prefix, 5)

	def validate(self):
		validate_request(self)

	def before_cancel(self):
		validate_request_cancel(self)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def get_employee_bank_account_query(
	doctype,
	txt,
	searchfield,
	start,
	page_len,
	filters,
	reference_doctype=None,
	ignore_user_permissions=False,
):
	"""Link search: only Bank Account rows for the selected Employee (excludes company / other parties)."""
	doctype = "Bank Account"
	if isinstance(filters, str):
		filters = json.loads(filters)
	filters = filters or {}
	employee = filters.get("employee")
	company = filters.get("company")

	conds = [
		"`tabBank Account`.party_type = %(party_type)s",
		"`tabBank Account`.docstatus != 2",
		"IFNULL(`tabBank Account`.disabled, 0) = 0",
	]
	values = {
		"party_type": "Employee",
		"txt": f"%{txt}%",
		"start": start,
		"page_len": page_len,
	}

	if employee:
		conds.append("`tabBank Account`.party = %(employee)s")
		values["employee"] = employee
	else:
		conds.append("1=0")

	if company:
		conds.append("`tabBank Account`.company = %(company)s")
		values["company"] = company

	where_sql = " AND ".join(conds)
	match_cond = get_match_cond(doctype)

	return frappe.db.sql(
		f"""
		SELECT `tabBank Account`.name, `tabBank Account`.account_name
		FROM `tabBank Account`
		WHERE {where_sql}
			AND `tabBank Account`.{searchfield} LIKE %(txt)s
			{match_cond}
		ORDER BY `tabBank Account`.name
		LIMIT %(page_len)s OFFSET %(start)s
		""",
		values,
	)


@frappe.whitelist()
def get_pm_request_holder_context(employee: str | None = None, company: str | None = None, posting_date=None) -> dict:
	return get_holder_context(employee, company, posting_date=posting_date)


@frappe.whitelist()
def create_payment_entry(pm_request: str):
	return create_payment_entry_service(pm_request)


@frappe.whitelist()
def get_pm_request_action_flags(pm_request: str):
	return get_pm_request_action_flags_service(pm_request)
