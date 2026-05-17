from __future__ import annotations

"""Configurable accounting narrations for Petty Management (PM Settings templates)."""

from typing import Any

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate, today

from erpnext_extensions.petty_management.services.narration_templates import (
	compose_accounting_narration,
	render_pm_template,
)
from erpnext_extensions.petty_management.utils import get_pm_settings

PM_NARRATION_PLACEHOLDER_HELP = (
	"Placeholders: {employee}, {employee_name}, {pm_request}, {pm_clearance}, {company}, "
	"{posting_date}, {total_amount}, {supplier}, {purchase_invoice}, {currency}. "
	"Leave empty to use the built-in default narration."
)


def _fmt_amount(amount: float, currency: str | None) -> str:
	if currency:
		return frappe.utils.fmt_money(flt(amount), currency=currency)
	return str(flt(amount))


def _employee_name(employee: str | None) -> str:
	if not employee:
		return ""
	return frappe.db.get_value("Employee", employee, "employee_name") or employee


def _company_currency(company: str | None) -> str:
	if not company:
		return ""
	return frappe.db.get_value("Company", company, "default_currency") or ""


def context_for_pm_request(doc: Document, amount: float) -> dict[str, Any]:
	currency = _company_currency(doc.company)
	posting = getdate(doc.transaction_date or today())
	return {
		"employee": doc.employee or "",
		"employee_name": _employee_name(doc.employee),
		"pm_request": doc.name or "",
		"pm_clearance": "",
		"company": doc.company or "",
		"posting_date": posting,
		"total_amount": _fmt_amount(amount, currency),
		"supplier": "",
		"purchase_invoice": "",
		"currency": currency,
	}


def context_for_pm_clearance(doc: Document) -> dict[str, Any]:
	suppliers: list[str] = []
	purchase_invoices: list[str] = []
	for row in doc.details or []:
		s = (getattr(row, "supplier", None) or "").strip()
		if s and s not in suppliers:
			suppliers.append(s)
		pi = (getattr(row, "purchase_invoice", None) or "").strip()
		if pi and pi not in purchase_invoices:
			purchase_invoices.append(pi)
	currency = (doc.currency or "").strip() or _company_currency(doc.company)
	posting = getdate(doc.je_clearance_date or doc.transaction_date or today())
	return {
		"employee": doc.employee or "",
		"employee_name": _employee_name(doc.employee),
		"pm_request": "",
		"pm_clearance": doc.name or "",
		"company": doc.company or "",
		"posting_date": posting,
		"total_amount": _fmt_amount(flt(doc.total_expense_amount), currency),
		"supplier": ", ".join(suppliers),
		"purchase_invoice": ", ".join(purchase_invoices),
		"currency": currency,
	}


def apply_funding_payment_entry_remarks(pe: Document, pm_request_doc: Document, amount: float) -> None:
	"""Apply PM narration to Payment Entry; requires custom_remarks so ERPNext does not overwrite."""
	text = build_funding_payment_entry_remarks(pm_request_doc, amount)
	meta_pe = frappe.get_meta("Payment Entry")
	if meta_pe.has_field("custom_remarks"):
		pe.custom_remarks = 1
	pe.remarks = text


def apply_settlement_journal_entry_remarks(je: Document, pm_clearance_doc: Document) -> None:
	"""Journal Entry visible narration is driven by user_remark (remark is built on validate)."""
	text = build_settlement_journal_entry_user_remark(pm_clearance_doc)
	je.user_remark = text
	if frappe.get_meta("Journal Entry").has_field("remark"):
		# Pre-fill so UI shows content before validate; validate may rebuild from lines + user_remark.
		je.remark = text


def build_funding_payment_entry_remarks(doc: Document, amount: float) -> str:
	settings = get_pm_settings()
	template = getattr(settings, "funding_payment_entry_remark_template", None) if settings else None
	fallback = _("Petty cash advance for {0}").format(doc.name)
	ctx = context_for_pm_request(doc, amount)
	system = render_pm_template(template, ctx, fallback=fallback)

	meta_pe = frappe.get_meta("Payment Entry")
	if doc.employee_bank_account and meta_pe.has_field("party_bank_account"):
		ba_ref = frappe.db.get_value("Bank Account", doc.employee_bank_account, "account_name") or str(
			doc.employee_bank_account
		)
		system = (system + "\n" + _("Employee Bank Account: {0}").format(ba_ref)).strip()

	user_remark = getattr(doc, "remark", None)
	return compose_accounting_narration(system, user_remark)


def build_settlement_journal_entry_user_remark(doc: Document) -> str:
	settings = get_pm_settings()
	template = getattr(settings, "settlement_journal_entry_remark_template", None) if settings else None
	fallback = _("Petty cash clearance {0}").format(doc.name)
	ctx = context_for_pm_clearance(doc)
	system = render_pm_template(template, ctx, fallback=fallback)
	user_remark = getattr(doc, "remark", None)
	return compose_accounting_narration(system, user_remark)
