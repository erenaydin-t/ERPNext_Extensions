"""Purchase Invoice / Purchase Order link search for PM Clearance settlement lines."""

from __future__ import annotations

from typing import Any

import frappe
from frappe import _
from frappe.utils import cint, flt, formatdate
from frappe.utils.formatters import format_value


def _parse_filters(filters) -> dict:
	if isinstance(filters, str):
		filters = frappe.parse_json(filters) if filters else {}
	return filters or {}


def _company_currency(company: str) -> str | None:
	return frappe.db.get_value("Company", company, "default_currency")


def _format_currency(amount: float, company: str) -> str:
	currency = _company_currency(company)
	return format_value(
		flt(amount),
		{"fieldtype": "Currency", "options": currency},
		currency=currency,
	)


def _supplier_display_name(supplier: str, supplier_name: str | None) -> str:
	name = (supplier_name or "").strip()
	if not name:
		name = frappe.db.get_value("Supplier", supplier, "supplier_name") or supplier
	return name


def _pi_search_description(
	*,
	supplier_name: str,
	supplier: str,
	outstanding: float,
	posting_date,
	company: str,
) -> str:
	parts = [
		f"{supplier_name} | {supplier}",
		_("Outstanding: {0}").format(_format_currency(outstanding, company)),
	]
	if posting_date:
		parts.append(_("Posting Date: {0}").format(formatdate(posting_date)))
	return " · ".join(parts)


def _po_search_description(
	*,
	supplier_name: str,
	supplier: str,
	grand_total: float,
	advance_paid: float,
	transaction_date,
	company: str,
) -> str:
	remaining = max(0.0, flt(grand_total) - flt(advance_paid))
	parts = [
		f"{supplier_name} | {supplier}",
		_("PO Total: {0}").format(_format_currency(grand_total, company)),
		_("Advance Paid: {0}").format(_format_currency(advance_paid, company)),
		_("Remaining: {0}").format(_format_currency(remaining, company)),
	]
	if transaction_date:
		parts.append(_("Transaction Date: {0}").format(formatdate(transaction_date)))
	return " · ".join(parts)


def _pi_supplier_name_sql() -> str:
	if frappe.db.has_column("Purchase Invoice", "supplier_name"):
		return "IFNULL(NULLIF(pi.supplier_name, ''), s.supplier_name)"
	return "IFNULL(s.supplier_name, '')"


def _po_supplier_name_sql() -> str:
	if frappe.db.has_column("Purchase Order", "supplier_name"):
		return "IFNULL(NULLIF(po.supplier_name, ''), s.supplier_name)"
	return "IFNULL(s.supplier_name, '')"


def _pi_supplier_name_search_sql() -> str:
	if frappe.db.has_column("Purchase Invoice", "supplier_name"):
		return "OR IFNULL(pi.supplier_name, '') LIKE %(txt)s"
	return ""


def _po_supplier_name_search_sql() -> str:
	if frappe.db.has_column("Purchase Order", "supplier_name"):
		return "OR IFNULL(po.supplier_name, '') LIKE %(txt)s"
	return ""


def purchase_invoice_query_for_pm_clearance(doctype, txt, searchfield, start, page_len, filters):
	if doctype != "Purchase Invoice":
		return []
	filters = _parse_filters(filters)
	company = filters.get("company")
	if not company:
		return []

	params: dict[str, Any] = {
		"company": company,
		"txt": f"%{txt}%",
		"start": cint(start),
		"page_len": cint(page_len),
		"min_outstanding": flt(filters.get("min_outstanding", 0)) or 0.0001,
	}
	conditions = [
		"pi.docstatus = 1",
		"pi.company = %(company)s",
		"IFNULL(pi.outstanding_amount, 0) > %(min_outstanding)s",
	]
	if filters.get("supplier"):
		conditions.append("pi.supplier = %(supplier)s")
		params["supplier"] = filters["supplier"]
	if txt:
		conditions.append(
			f"""(
				pi.name LIKE %(txt)s
				OR pi.supplier LIKE %(txt)s
				OR IFNULL(s.supplier_name, '') LIKE %(txt)s
				{_pi_supplier_name_search_sql()}
				OR IFNULL(pi.bill_no, '') LIKE %(txt)s
			)"""
		)
	where = " AND ".join(conditions)
	sname_sql = _pi_supplier_name_sql()
	rows = frappe.db.sql(
		f"""
		SELECT
			pi.name,
			pi.supplier,
			{sname_sql} AS supplier_name,
			pi.outstanding_amount,
			pi.posting_date
		FROM `tabPurchase Invoice` pi
		LEFT JOIN `tabSupplier` s ON s.name = pi.supplier
		WHERE {where}
		ORDER BY pi.posting_date DESC, pi.modified DESC
		LIMIT %(page_len)s OFFSET %(start)s
		""",
		params,
		as_dict=True,
	)
	out = []
	for row in rows:
		sname = _supplier_display_name(row.supplier, row.supplier_name)
		desc = _pi_search_description(
			supplier_name=sname,
			supplier=row.supplier,
			outstanding=flt(row.outstanding_amount),
			posting_date=row.posting_date,
			company=company,
		)
		out.append([row.name, desc])
	return out


def purchase_order_query_for_pm_clearance(doctype, txt, searchfield, start, page_len, filters):
	if doctype != "Purchase Order":
		return []
	filters = _parse_filters(filters)
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
		"po.docstatus = 1",
		"po.company = %(company)s",
	]
	if filters.get("supplier"):
		conditions.append("po.supplier = %(supplier)s")
		params["supplier"] = filters["supplier"]
	if txt:
		conditions.append(
			f"""(
				po.name LIKE %(txt)s
				OR po.supplier LIKE %(txt)s
				OR IFNULL(s.supplier_name, '') LIKE %(txt)s
				{_po_supplier_name_search_sql()}
			)"""
		)
	where = " AND ".join(conditions)
	sname_sql = _po_supplier_name_sql()
	rows = frappe.db.sql(
		f"""
		SELECT
			po.name,
			po.supplier,
			{sname_sql} AS supplier_name,
			IFNULL(po.grand_total, 0) AS grand_total,
			IFNULL(po.advance_paid, 0) AS advance_paid,
			po.transaction_date
		FROM `tabPurchase Order` po
		LEFT JOIN `tabSupplier` s ON s.name = po.supplier
		WHERE {where}
		ORDER BY po.transaction_date DESC, po.modified DESC
		LIMIT %(page_len)s OFFSET %(start)s
		""",
		params,
		as_dict=True,
	)
	out = []
	for row in rows:
		sname = _supplier_display_name(row.supplier, row.supplier_name)
		desc = _po_search_description(
			supplier_name=sname,
			supplier=row.supplier,
			grand_total=flt(row.grand_total),
			advance_paid=flt(row.advance_paid),
			transaction_date=row.transaction_date,
			company=company,
		)
		out.append([row.name, desc])
	return out
