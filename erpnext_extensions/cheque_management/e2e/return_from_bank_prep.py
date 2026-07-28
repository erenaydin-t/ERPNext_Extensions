"""Prep helpers for Return from Bank Playwright E2E."""

from __future__ import annotations

from datetime import timedelta

import frappe
from frappe.utils import getdate, today

from erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque import (
	_get_pdc_settings_for_company,
	get_default_party_accounts,
)
from erpnext_extensions.cheque_management.pdc_journal_entry_service import post_pdc_transition_journal_entry
from erpnext_extensions.cheque_management.pdc_workflow_state_machine import (
	WORKFLOW_DRAFT,
	WORKFLOW_REGISTERED,
	WORKFLOW_SENT_TO_BANK,
)


def prep_return_from_bank_bundle() -> dict:
	"""Create Receivable PDC at Sent to Bank ready for Return from Bank."""
	frappe.set_user("Administrator")
	company = frappe.db.get_value("Company", {}, "name", order_by="creation asc")
	customer = frappe.db.get_value("Customer", {"disabled": 0}, "name", order_by="modified desc")
	bank_account = frappe.db.get_value(
		"Bank Account",
		{"company": company, "disabled": 0, "is_company_account": 1},
		"name",
		order_by="modified desc",
	)
	drawer_bank = frappe.db.get_value("Bank", {}, "name", order_by="modified desc")
	settings = _get_pdc_settings_for_company(company)
	acc = get_default_party_accounts("Customer", customer, company, "Receivable") or {}

	doc = frappe.new_doc("Post Dated Cheque")
	doc.cheque_direction = "Receivable"
	doc.company = company
	doc.party_type = "Customer"
	doc.party = customer
	doc.cheque_no = f"RFB-UI-{frappe.generate_hash(length=8)}"
	doc.cheque_due_date = getdate(today()) + timedelta(days=20)
	doc.cheque_amount = 777
	doc.received_date = today()
	doc.drawer_bank_name = drawer_bank
	doc.bank_account = bank_account
	doc.account_paid_to = acc.get("account_paid_to") or settings.default_cheques_in_hand_account
	doc.account_paid_from = acc.get("account_paid_from")
	doc.workflow_state = WORKFLOW_DRAFT
	doc.allocation_mode = "direct_settlement"
	doc.cheque_purpose = "UI Return from Bank purpose"
	doc.sayad_code = f"SAYAD-{doc.cheque_no}"[:32]
	doc.sayad_registered = 1
	doc.insert(ignore_permissions=True)
	frappe.db.commit()

	doc.workflow_state = WORKFLOW_REGISTERED
	doc.flags.ignore_validate_update_after_submit = True
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	post_pdc_transition_journal_entry(doc, WORKFLOW_DRAFT, WORKFLOW_REGISTERED, posting_date=today())
	frappe.db.commit()

	doc.reload()
	doc.sent_to_bank_date = today()
	doc.workflow_state = WORKFLOW_SENT_TO_BANK
	doc.flags.ignore_validate_update_after_submit = True
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	post_pdc_transition_journal_entry(doc, WORKFLOW_REGISTERED, WORKFLOW_SENT_TO_BANK, posting_date=today())
	frappe.db.commit()
	doc.reload()

	return {
		"pdc_name": doc.name,
		"today": today(),
		"workflow_state": doc.workflow_state,
		"cheque_purpose": doc.cheque_purpose,
	}


def e2e_resend_and_return_cycle(pdc_name: str) -> dict:
	"""From Registered (after Return): Send→Return again; report JE counts."""
	frappe.set_user("Administrator")
	doc = frappe.get_doc("Post Dated Cheque", pdc_name)
	if normalize_workflow_state(doc.workflow_state) != WORKFLOW_REGISTERED:
		doc.workflow_state = WORKFLOW_REGISTERED
		doc.flags.ignore_validate_update_after_submit = True
		doc.save(ignore_permissions=True)
		frappe.db.commit()
		doc.reload()

	doc.sent_to_bank_date = today()
	doc.workflow_state = WORKFLOW_SENT_TO_BANK
	doc.flags.ignore_validate_update_after_submit = True
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	doc.reload()
	post_pdc_transition_journal_entry(doc, WORKFLOW_REGISTERED, WORKFLOW_SENT_TO_BANK, posting_date=today())
	frappe.db.commit()

	doc.reload()
	doc.returned_from_bank_date = today()
	doc.workflow_state = WORKFLOW_REGISTERED
	doc.flags.ignore_validate_update_after_submit = True
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	doc.reload()
	post_pdc_transition_journal_entry(doc, WORKFLOW_SENT_TO_BANK, WORKFLOW_REGISTERED, posting_date=today())
	frappe.db.commit()

	send_jes = frappe.get_all(
		"PDC Journal Reference",
		filters={"parent": pdc_name, "purpose": "Under Collection"},
		pluck="journal_entry",
	)
	return_jes = frappe.get_all(
		"PDC Journal Reference",
		filters={"parent": pdc_name, "purpose": "Return from Bank"},
		pluck="journal_entry",
	)
	return {
		"ok": len(set(send_jes)) >= 2 and len(set(return_jes)) >= 2,
		"send_jes": len(set(send_jes)),
		"return_jes": len(set(return_jes)),
		"workflow_state": frappe.db.get_value("Post Dated Cheque", pdc_name, "workflow_state"),
	}


def normalize_workflow_state(value: str | None) -> str:
	from erpnext_extensions.cheque_management.pdc_workflow_state_machine import (
		normalize_workflow_state_value,
	)

	return normalize_workflow_state_value(value)
