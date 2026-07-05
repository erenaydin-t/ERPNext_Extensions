"""Debug PDC transition posting (integration harness parity)."""

from __future__ import annotations

import json
import time
from datetime import date, timedelta

import frappe

from erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque import (
	build_pdc_journal_entry_data,
	get_accounting_action,
)
from erpnext_extensions.cheque_management.pdc_accounting_idempotency import (
	build_pdc_accounting_transition_key,
)
from erpnext_extensions.cheque_management.pdc_journal_entry_service import (
	get_existing_journal_entry_for_transition,
	post_pdc_transition_journal_entry,
)
from erpnext_extensions.cheque_management.pdc_workflow_state_machine import (
	PDC_ACCOUNTING_JOURNAL_ENTRY,
	PDC_ACCOUNTING_NO_DOCUMENT,
	get_pdc_accounting_decision,
)


def _refs(pdc_name: str) -> list[dict]:
	return frappe.get_all(
		"PDC Journal Reference",
		filters={"parent": pdc_name, "parenttype": "Post Dated Cheque"},
		fields=["name", "journal_entry", "purpose", "pdc_transition_key", "posting_date"],
		order_by="creation asc",
	)


def _gl_for_je(je: str | None) -> list[dict]:
	if not je:
		return []
	return frappe.get_all(
		"GL Entry",
		filters={"voucher_no": je, "is_cancelled": 0},
		fields=["name", "account", "debit", "credit"],
		limit=20,
	)


def _debug_transition(
	pdc_name: str,
	from_state: str,
	to_state: str,
	*,
	extra_save=None,
) -> dict:
	doc = frappe.get_doc("Post Dated Cheque", pdc_name)
	before_ws = doc.workflow_state
	refs_before = _refs(pdc_name)

	settings_name = frappe.db.get_value("PDC Settings", {"company": doc.company}, "name")
	settings = frappe.get_doc("PDC Settings", settings_name) if settings_name else None

	prev_for_acct = doc.get_value_before_save("workflow_state")
	decision = get_pdc_accounting_decision(doc.cheque_direction, before_ws, to_state)
	action = get_accounting_action(doc, before_ws)

	payload = build_pdc_journal_entry_data(doc, before_ws, to_state, posting_date=date.today())
	existing_je = get_existing_journal_entry_for_transition(
		pdc_name, doc.cheque_direction, before_ws, to_state
	)

	out = {
		"pdc_name": pdc_name,
		"cheque_direction": doc.cheque_direction,
		"workflow_state_before": before_ws,
		"workflow_state_target": to_state,
		"bank_account": doc.bank_account,
		"account_paid_from": doc.account_paid_from,
		"account_paid_to": getattr(doc, "account_paid_to", None),
		"pdc_settings": settings.as_dict() if settings else None,
		"get_pdc_accounting_decision": decision,
		"get_accounting_action": (
			PDC_ACCOUNTING_NO_DOCUMENT if action == PDC_ACCOUNTING_NO_DOCUMENT else PDC_ACCOUNTING_JOURNAL_ENTRY
		),
		"build_pdc_journal_entry_data": payload,
		"existing_je_for_transition": existing_je,
		"refs_before": refs_before,
		"idempotency_key": build_pdc_accounting_transition_key(
			pdc_name, doc.cheque_direction, before_ws, to_state
		),
		"get_value_before_save_workflow_state": prev_for_acct,
	}

	if extra_save:
		extra_save(doc)
		doc.save(ignore_permissions=True)
		doc.reload()

	# Simulate post-save path (what on_update_after_submit would do after workflow save)
	je_name = post_pdc_transition_journal_entry(
		doc, before_ws, to_state, posting_date=getattr(doc, "cleared_date", None)
		or getattr(doc, "sent_to_bank_date", None)
		or date.today()
	)
	doc.reload()
	refs_after = _refs(pdc_name)

	out["post_pdc_transition_journal_entry_return"] = je_name
	out["refs_after_manual_post"] = refs_after
	out["gl_for_new_je"] = _gl_for_je(je_name)
	return out


def debug_payable_issued_to_cleared():
	"""Run minimal payable path to Issued, then debug Cleared posting."""
	from erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque import (
		PostDatedCheque,
		get_accounting_action,
	)
	from erpnext_extensions.cheque_management.tests import test_pdc_workflow_rollback_lifecycle_integration as life

	post_save_logs = []
	_orig = PostDatedCheque._pdc_post_save_accounting_sequence

	post_calls = []

	def _log_post_save(self):
		prev_cap = getattr(self, "_pdc_previous_workflow_for_accounting", None)
		prev_gvs = self.get_value_before_save("workflow_state")
		prev_raw = self._get_previous_workflow_state_raw()
		prev_acct = self._get_previous_workflow_state_for_accounting()
		prev_use = prev_cap if prev_cap is not None else prev_acct if prev_acct is not None else prev_raw
		action = get_accounting_action(self, prev_use)
		entry = {
			"prev_captured": prev_cap,
			"prev_gvs": prev_gvs,
			"prev_raw": prev_raw,
			"prev_acct": prev_acct,
			"curr": self.workflow_state,
			"action": action,
			"has_doc_before_save": self.get_doc_before_save() is not None,
		}
		if action == "journal_entry" and prev_use is not None:
			from erpnext_extensions.cheque_management.pdc_journal_entry_service import (
				get_existing_journal_entry_for_transition,
			)

			entry["existing_je_before_post"] = get_existing_journal_entry_for_transition(
				self.name, self.cheque_direction, prev_use, self.workflow_state
			)
		post_save_logs.append(entry)
		_orig(self)
		entry["refs_after"] = len(_refs(self.name))
		post_save_logs[-1] = entry
		return None

	PostDatedCheque._pdc_post_save_accounting_sequence = _log_post_save

	import erpnext_extensions.cheque_management.pdc_journal_entry_service as je_svc

	_orig_post = je_svc.post_pdc_transition_journal_entry

	def _log_post(pdc, from_state, to_state, **kwargs):
		out = _orig_post(pdc, from_state, to_state, **kwargs)
		post_calls.append(
			{"from": from_state, "to": to_state, "return": out, "kwargs": kwargs}
		)
		return out

	je_svc.post_pdc_transition_journal_entry = _log_post

	frappe.set_user("Administrator")
	company = life._get_company()
	bank_account = life._get_bank_account(company)
	assets = life._get_group_account(company, "Asset")
	liab = life._get_group_account(company, "Liability")
	ci_hand = life._get_or_create_account(company, assets, life._uniq("DBG-CIH"))
	ci_clear = life._get_or_create_account(company, assets, life._uniq("DBG-CLR"))
	protested = life._get_or_create_account(company, assets, life._uniq("DBG-PROT"))
	pool = life._get_or_create_account(company, liab, life._uniq("DBG-POOL"))
	ap = life._get_or_create_account(company, liab, life._uniq("DBG-AP"))
	life._ensure_pdc_settings(company, ci_hand=ci_hand, ci_clear=ci_clear, pool=pool, protested=protested)

	leaf = life._provision_payable_leaf(company, bank_account)
	case = life.TestPDCWorkflowRollbackLifecycleIntegration()
	pdc_name = case._make_payable_pdc(company, bank_account, leaf, pool, ap)
	doc = frappe.get_doc("Post Dated Cheque", pdc_name)
	from frappe.model.workflow import apply_workflow

	doc = apply_workflow(doc, "Register Cheque")
	doc = life._issue_payable(doc)
	doc.reload()

	refs_at_issued = _refs(pdc_name)

	def set_cleared(d):
		if not d.cleared_date:
			d.cleared_date = date.today()

	# Workflow transition (production path)
	set_cleared(doc)
	doc.save(ignore_permissions=True)
	doc.reload()
	doc = apply_workflow(doc, "Clear Cheque")
	doc.reload()

	refs_after_workflow = _refs(pdc_name)
	ws_before_clear = "Issued"  # known from path

	debug = _debug_transition(pdc_name, ws_before_clear, "Cleared")

	return {
		"refs_after_register_issue": refs_at_issued,
		"refs_after_apply_workflow_clear": refs_after_workflow,
		"workflow_after_clear": doc.workflow_state,
		"post_save_logs": post_save_logs,
		"post_pdc_transition_calls": post_calls,
		"manual_post_debug": debug,
	}


def debug_receivable_registered_to_sent_to_bank():
	from erpnext_extensions.cheque_management.tests import test_pdc_workflow_rollback_lifecycle_integration as life

	frappe.set_user("Administrator")
	company = life._get_company()
	bank_account = life._get_bank_account(company)
	assets = life._get_group_account(company, "Asset")
	ci_hand = life._get_or_create_account(company, assets, life._uniq("DBG-CIH-R"))
	ci_clear = life._get_or_create_account(company, assets, life._uniq("DBG-CLR-R"))
	protested = life._get_or_create_account(company, assets, life._uniq("DBG-PROT-R"))
	ar = life._get_or_create_account(company, assets, life._uniq("DBG-AR"))
	life._ensure_pdc_settings(company, ci_hand=ci_hand, ci_clear=ci_clear, pool=ci_hand, protested=protested)

	case = life.TestPDCWorkflowRollbackLifecycleIntegration()
	pdc_name = case._make_receivable_pdc(company, bank_account, ar)
	from frappe.model.workflow import apply_workflow

	doc = apply_workflow(frappe.get_doc("Post Dated Cheque", pdc_name), "Register Cheque")
	refs_reg = _refs(pdc_name)

	doc = life._send_receivable_to_bank(doc)
	doc.reload()
	refs_stb = _refs(pdc_name)

	return {
		"refs_after_register": refs_reg,
		"refs_after_send_to_bank": refs_stb,
		"workflow_state": doc.workflow_state,
		"manual_post_debug": _debug_transition(
			pdc_name, "Registered", "Sent to Bank", extra_save=lambda d: setattr(d, "sent_to_bank_date", date.today()) if not d.sent_to_bank_date else None
		),
	}
