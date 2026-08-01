# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

import frappe
from frappe.desk.reportview import get_match_cond

from erpnext_extensions.consignment_stock.material_loan.constants import F_IS_LOAN_ISSUE


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def material_loan_issue_query(doctype, txt, searchfield, start, page_len, filters):
	filters = filters or {}
	company = filters.get("company")
	party_type = filters.get("party_type")
	party = filters.get("party")
	conds = [f"se.{F_IS_LOAN_ISSUE} = 1", "se.docstatus = 1"]
	values = {"txt": f"%{txt}%", "start": start, "page_len": page_len}
	if company:
		conds.append("se.company = %(company)s")
		values["company"] = company
	if party_type:
		conds.append("se.custom_material_loan_party_type = %(party_type)s")
		values["party_type"] = party_type
	if party:
		conds.append("se.custom_material_loan_party = %(party)s")
		values["party"] = party
	return frappe.db.sql(
		f"""
		select se.name, se.posting_date
		from `tabStock Entry` se
		where {' and '.join(conds)}
		  and se.name like %(txt)s
		  {get_match_cond(doctype)}
		order by se.posting_date desc
		limit %(start)s, %(page_len)s
		""",
		values,
	)
