"""Purchase Invoice link search for PM Clearance settlement lines."""

from __future__ import annotations

from typing import Any

import frappe
from frappe.utils import cint, flt


def purchase_invoice_query_for_pm_clearance(doctype, txt, searchfield, start, page_len, filters):
	if doctype != "Purchase Invoice":
		return []
	if isinstance(filters, str):
		filters = frappe.parse_json(filters) if filters else {}
	filters = filters or {}

	company = filters.get("company")
	if not company:
		return []

	params: dict[str, Any] = {
		"company": company,
		"txt": f"%{txt}%",
		"start": cint(start),
		"page_len": cint(page_len),
	}
	conditions = [
		"pi.docstatus = 1",
		"pi.company = %(company)s",
		"IFNULL(pi.outstanding_amount, 0) > %(min_outstanding)s",
	]
	params["min_outstanding"] = flt(filters.get("min_outstanding", 0)) or 0.0001
	if filters.get("supplier"):
		conditions.append("pi.supplier = %(supplier)s")
		params["supplier"] = filters["supplier"]
	if txt:
		conditions.append(
			"(pi.name LIKE %(txt)s OR pi.supplier LIKE %(txt)s OR IFNULL(pi.bill_no, '') LIKE %(txt)s)"
		)
	where = " AND ".join(conditions)
	return frappe.db.sql(
		f"""
		SELECT pi.name, pi.supplier, pi.outstanding_amount
		FROM `tabPurchase Invoice` pi
		WHERE {where}
		ORDER BY pi.posting_date DESC, pi.modified DESC
		LIMIT %(page_len)s OFFSET %(start)s
		""",
		params,
	)
