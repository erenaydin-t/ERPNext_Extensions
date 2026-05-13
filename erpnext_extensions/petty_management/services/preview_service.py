from __future__ import annotations

import copy
from typing import Any

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate, today

from erpnext_extensions.petty_management.services.clearance_service import prepare_doc_for_je_preview
from erpnext_extensions.petty_management.services.journal_entry_service import build_clearance_je_accounts
from erpnext_extensions.petty_management.utils import get_pm_settings


def preview_pm_clearance_settlement(doc=None, pm_clearance: str | None = None) -> dict[str, Any]:
	source_doc = doc_for_preview(doc=doc, pm_clearance=pm_clearance)
	dobj = frappe.get_doc(copy.deepcopy(source_doc.as_dict()))
	prepare_doc_for_je_preview(dobj)
	accounts = build_clearance_je_accounts(dobj)
	settings = get_pm_settings()
	auto_submit = bool(settings and settings.auto_submit_journal_entry)
	for row in accounts:
		deb = flt(row.get("debit_in_account_currency"))
		cre = flt(row.get("credit_in_account_currency"))
		if deb > 0:
			row["line_type"] = "Debit"
		elif cre > 0:
			row["line_type"] = "Credit"
		else:
			row["line_type"] = ""
	total_credit = sum(flt(a.get("credit_in_account_currency")) for a in accounts)
	total_debit = sum(flt(a.get("debit_in_account_currency")) for a in accounts)
	return {
		"accounts": accounts,
		"total_debit": total_debit,
		"total_credit": total_credit,
		"company": dobj.company,
		"posting_date": str(getdate(dobj.je_clearance_date or dobj.transaction_date or today())),
		"pm_clearance": dobj.name or "",
		"auto_submit_journal_entry": auto_submit,
	}


def doc_for_preview(doc=None, pm_clearance: str | None = None) -> Document:
	if pm_clearance:
		dobj = frappe.get_doc("PM Clearance", pm_clearance)
		if not frappe.has_permission("PM Clearance", "read", doc=dobj):
			frappe.throw(_("Not permitted"), frappe.PermissionError)
		return dobj
	if not doc:
		frappe.throw(_("Document or PM Clearance name required"))
	raw = frappe.parse_json(doc)
	dobj = frappe.get_doc(raw)
	docname = getattr(dobj, "name", None)
	if docname and frappe.db.exists("PM Clearance", docname):
		if not frappe.has_permission("PM Clearance", "read", doc=docname):
			frappe.throw(_("Not permitted"), frappe.PermissionError)
	else:
		if not frappe.has_permission("PM Clearance", "create"):
			frappe.throw(_("Not permitted"), frappe.PermissionError)
	return dobj

