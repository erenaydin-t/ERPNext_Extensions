"""Prep helpers for Post Dated Cheque cheque_purpose Playwright E2E."""

from __future__ import annotations

import json

import frappe
from frappe.utils import today

from erpnext_extensions.cheque_management.doctype.cheque_opening_import.cheque_opening_import import (
	import_row,
)
from erpnext_extensions.cheque_management.doctype.cheque_opening_import.run_live_opening_import_accounting_e2e import (
	_base_payable_row,
	_base_receivable_row,
)
from erpnext_extensions.cheque_management.pdc_workflow_rollback import rollback_workflow_state
from erpnext_extensions.cheque_management.pdc_workflow_state_machine import WORKFLOW_ISSUED, WORKFLOW_REGISTERED
from erpnext_extensions.cheque_management.run_live_party_orchestration_e2e import (
	_new_payable_pdc,
	_new_receivable_pdc,
	_transition,
	_unique_cheque_no,
)
from erpnext_extensions.cheque_management.tests.cheque_purpose_context import (
	ensure_cheque_purpose_context,
)
from erpnext_extensions.e2e.e2e_unique import e2e_unique_tag


def prep_cheque_purpose_bundle() -> str:
	"""Create fixtures for cheque_purpose E2E. Returns JSON string."""
	frappe.set_user("Administrator")
	ctx = ensure_cheque_purpose_context()
	frappe.db.commit()
	company = ctx["company"]

	payable_purpose = "تسویه فاکتور خرید شماره PI-E2E-PURPOSE"
	receivable_purpose = "دریافت بابت فروش فروردین E2E"
	search_phrase = f"E2E-PURPOSE-{e2e_unique_tag('PHRASE')}"
	import_purpose = f"Opening import purpose {search_phrase}"

	# Payable draft for UI edit / save / workflow
	pay = _new_payable_pdc(ctx, _unique_cheque_no("E2E-P-PURP"))
	pay.cheque_purpose = payable_purpose
	pay.save(ignore_permissions=True)
	frappe.db.commit()

	# Receivable draft with distinct purpose
	rec = _new_receivable_pdc(ctx, _unique_cheque_no("E2E-R-PURP"))
	rec.cheque_purpose = receivable_purpose
	rec.save(ignore_permissions=True)
	frappe.db.commit()

	# Searchable submitted payable with unique phrase
	search_doc = _new_payable_pdc(ctx, _unique_cheque_no("E2E-S-PURP"))
	search_doc.cheque_purpose = f"Settlement for {search_phrase}"
	search_doc.save(ignore_permissions=True)
	frappe.db.commit()
	search_doc.reload()
	if search_doc.docstatus == 0:
		search_doc.submit()
		frappe.db.commit()
		search_doc.reload()
	_transition(search_doc, WORKFLOW_REGISTERED, received_date=today())
	frappe.db.commit()
	search_doc.reload()

	# Opening import with purpose
	chq_imp = _unique_cheque_no("E2E-OI-P")
	row = _base_payable_row(ctx, chq_imp, "Draft", cheque_purpose=import_purpose)
	coi = frappe.new_doc("Cheque Opening Import")
	coi.insert(ignore_permissions=True)
	frappe.flags.cheque_opening_import_name = coi.name
	try:
		imported_pdc = import_row(1, row)
	finally:
		if hasattr(frappe.flags, "cheque_opening_import_name"):
			delattr(frappe.flags, "cheque_opening_import_name")
	frappe.db.commit()

	# Opening import without purpose (compat)
	chq_old = _unique_cheque_no("E2E-OI-OLD")
	row_old = _base_receivable_row(ctx, chq_old, "Draft")
	row_old.pop("cheque_purpose", None)
	coi2 = frappe.new_doc("Cheque Opening Import")
	coi2.insert(ignore_permissions=True)
	frappe.flags.cheque_opening_import_name = coi2.name
	try:
		imported_old = import_row(1, row_old)
	finally:
		if hasattr(frappe.flags, "cheque_opening_import_name"):
			delattr(frappe.flags, "cheque_opening_import_name")
	frappe.db.commit()

	# Payable at Issued for rollback purpose preservation
	rb = _new_payable_pdc(ctx, _unique_cheque_no("E2E-RB-PURP"))
	rb.cheque_purpose = payable_purpose
	rb.save(ignore_permissions=True)
	frappe.db.commit()
	rb.reload()
	if rb.docstatus == 0:
		rb.submit()
		frappe.db.commit()
		rb.reload()
	_transition(rb, WORKFLOW_REGISTERED, received_date=today())
	rb.reload()
	_transition(rb, WORKFLOW_ISSUED, handover_date=today())
	rb.reload()

	out = {
		"ok": True,
		"company": company,
		"payable_draft": pay.name,
		"payable_purpose": payable_purpose,
		"receivable_draft": rec.name,
		"receivable_purpose": receivable_purpose,
		"search_pdc": search_doc.name,
		"search_phrase": search_phrase,
		"imported_pdc": imported_pdc,
		"import_purpose": import_purpose,
		"imported_old_pdc": imported_old,
		"rollback_pdc": rb.name,
		"rollback_purpose": payable_purpose,
		"rollback_state": rb.workflow_state,
	}
	return out


def e2e_sql_verify_cheque_purpose(pdc_names: list | str | None = None) -> dict:
	"""Return SQL evidence rows for cheque_purpose."""
	names = pdc_names
	if isinstance(names, str):
		try:
			names = json.loads(names)
		except Exception:
			names = [names]
	names = [n for n in (names or []) if n]
	if not names:
		return {"ok": False, "error": "no names"}
	rows = frappe.db.sql(
		"""
		SELECT name, cheque_direction, cheque_purpose, workflow_state, docstatus
		FROM `tabPost Dated Cheque`
		WHERE name IN %s
		ORDER BY name
		""",
		(tuple(names),),
		as_dict=True,
	)
	return {"ok": True, "rows": rows}


def e2e_advance_payable_to_registered(pdc_name: str) -> dict:
	from erpnext_extensions.cheque_management.run_live_party_orchestration_e2e import _transition
	from erpnext_extensions.cheque_management.pdc_workflow_state_machine import WORKFLOW_REGISTERED

	doc = frappe.get_doc("Post Dated Cheque", pdc_name)
	if doc.docstatus == 0:
		doc.submit()
		frappe.db.commit()
		doc.reload()
	if (doc.workflow_state or "") == "Draft":
		_transition(doc, WORKFLOW_REGISTERED, received_date=today())
		doc.reload()
	return {
		"ok": True,
		"name": doc.name,
		"workflow_state": doc.workflow_state,
		"cheque_purpose": doc.cheque_purpose,
		"docstatus": doc.docstatus,
	}


def e2e_rollback_issued_to_registered(pdc_name: str) -> dict:
	doc = frappe.get_doc("Post Dated Cheque", pdc_name)
	purpose_before = doc.cheque_purpose
	rollback_workflow_state(pdc_name, "Registered", "E2E cheque purpose rollback")
	frappe.db.commit()
	doc.reload()
	return {
		"ok": True,
		"name": doc.name,
		"workflow_state": doc.workflow_state,
		"cheque_purpose": doc.cheque_purpose,
		"purpose_before": purpose_before,
		"purpose_preserved": doc.cheque_purpose == purpose_before,
	}
