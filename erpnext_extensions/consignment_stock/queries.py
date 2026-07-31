# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

import frappe
from frappe.utils import flt

from erpnext_extensions.consignment_stock.constants import (
	F_IS_RECEIPT,
	F_PARTY,
	F_PARTY_TYPE,
	F_RECOGNITION_JE,
)
from erpnext_extensions.consignment_stock.returnable_qty import get_remaining_returnable_qty


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def consignment_receipt_query(doctype, txt, searchfield, start, page_len, filters):
	filters = filters or {}
	company = filters.get("company")
	party_type = filters.get("party_type")
	party = filters.get("party")

	conditions = [
		"se.docstatus = 1",
		f"se.`{F_IS_RECEIPT}` = 1",
	]
	values = {"txt": f"%{txt}%", "start": start, "page_len": page_len}

	if company:
		conditions.append("se.company = %(company)s")
		values["company"] = company
	if party_type:
		conditions.append(f"se.`{F_PARTY_TYPE}` = %(party_type)s")
		values["party_type"] = party_type
	if party:
		conditions.append(f"se.`{F_PARTY}` = %(party)s")
		values["party"] = party

	conditions.append(
		f"""exists (
			select 1 from `tabJournal Entry` je
			where je.name = se.`{F_RECOGNITION_JE}` and je.docstatus = 1
		)"""
	)

	where = " and ".join(conditions)
	return frappe.db.sql(
		f"""
		select se.name, se.posting_date, se.`{F_PARTY}`
		from `tabStock Entry` se
		where {where}
			and se.name like %(txt)s
		order by se.posting_date desc, se.name desc
		limit %(start)s, %(page_len)s
		""",
		values,
	)


@frappe.whitelist()
def get_receipt_row_returnable_qty(receipt_detail: str, exclude_return: str | None = None) -> dict:
	remaining = get_remaining_returnable_qty(receipt_detail, exclude_return_name=exclude_return)
	original = flt(
		frappe.db.get_value("Stock Entry Detail", receipt_detail, "transfer_qty")
		or frappe.db.get_value("Stock Entry Detail", receipt_detail, "qty")
	)
	return {
		"receipt_detail": receipt_detail,
		"original_qty": original,
		"remaining_returnable_qty": remaining,
	}
