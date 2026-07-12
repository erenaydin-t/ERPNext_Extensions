"""Live E2E: Payable PDC Cheque Leaf — Used-by-same-PDC across workflow states.

bench --site development.localhost execute erpnext_extensions.cheque_management.run_live_pdc_cheque_leaf_e2e.run
"""

from __future__ import annotations

import json
import time
from datetime import timedelta

import frappe
from frappe.utils import getdate, today

from erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque import (
	_get_pdc_settings_for_company,
	get_default_party_accounts,
)
from erpnext_extensions.cheque_management.pdc_accounting_idempotency import (
	build_pdc_accounting_transition_key,
)
from erpnext_extensions.cheque_management.pdc_journal_entry_service import (
	post_pdc_transition_journal_entry,
)
from erpnext_extensions.cheque_management.pdc_workflow_state_machine import (
	WORKFLOW_CANCELLED,
	WORKFLOW_CLEARED,
	WORKFLOW_DRAFT,
	WORKFLOW_ISSUED,
	WORKFLOW_REGISTERED,
	WORKFLOW_RETURNED,
	normalize_workflow_state_value,
)


def _today():
	return getdate(today())


def _leaf_sql(leaf_name: str) -> dict:
	rows = frappe.db.sql(
		"""
		select name, status, reserved_by_pdc, linked_post_dated_cheque, cheque_number
		from `tabCheque Leaf` where name = %s
		""",
		(leaf_name,),
		as_dict=True,
	)
	return dict(rows[0]) if rows else {}


def _find_or_note_available_leaf(company: str, bank_account: str) -> str | None:
	return frappe.db.get_value(
		"Cheque Leaf",
		{"status": "Available", "company": company, "bank_account": bank_account},
		"name",
		order_by="modified desc",
	)


def _provision_available_leaf(company: str, bank_account: str) -> str:
	existing = _find_or_note_available_leaf(company, bank_account)
	if existing:
		return existing

	start = int(time.time()) % 900000 + 100000
	book = frappe.new_doc("Cheque Book")
	book.company = company
	book.bank_account = bank_account
	book.generation_mode = "prefix_plus_sequence"
	book.start_number = start
	book.end_number = start
	book.number_width = 6
	book.insert(ignore_permissions=True)
	book.generate_leaves()
	frappe.db.commit()
	leaf = frappe.db.get_value(
		"Cheque Leaf",
		{"cheque_book": book.name, "status": "Available"},
		"name",
		order_by="creation asc",
	)
	if not leaf:
		frappe.throw("Failed to provision Cheque Leaf for E2E")
	return leaf


def _cheque_no_for_leaf(leaf: str) -> str:
	cheque_no = (frappe.db.get_value("Cheque Leaf", leaf, "cheque_number") or "").strip()
	if not cheque_no:
		cheque_no = f"LIVE-CL-{int(time.time())}"
		frappe.db.set_value("Cheque Leaf", leaf, "cheque_number", cheque_no, update_modified=False)
	return cheque_no


def _new_payable_pdc(ctx: dict, cheque_no: str, cheque_leaf: str):
	acc = get_default_party_accounts("Supplier", ctx["supplier"], ctx["company"], "Payable") or {}
	doc = frappe.new_doc("Post Dated Cheque")
	doc.cheque_direction = "Payable"
	doc.company = ctx["company"]
	doc.party_type = "Supplier"
	doc.party = ctx["supplier"]
	doc.cheque_no = cheque_no
	doc.cheque_due_date = _today() + timedelta(days=30)
	doc.cheque_amount = 100.0
	doc.bank_account = ctx["bank_account"]
	doc.cheque_leaf = cheque_leaf
	doc.account_paid_to = acc.get("account_paid_to")
	doc.account_paid_from = acc.get("account_paid_from") or ctx["settings"].default_payable_cheque_account
	doc.workflow_state = WORKFLOW_DRAFT
	doc.allocation_mode = "direct_settlement"
	doc.sayad_code = f"SAYAD-{cheque_no}"[:32]
	doc.sayad_registered = 1
	doc.insert(ignore_permissions=True)
	frappe.db.commit()
	return doc


def _je_for_transition(
	pdc_name: str, from_state: str, to_state: str, cheque_direction: str = "Payable"
) -> str | None:
	key = build_pdc_accounting_transition_key(pdc_name, cheque_direction, from_state, to_state)
	rows = frappe.get_all(
		"PDC Journal Reference",
		filters={"parent": pdc_name, "pdc_transition_key": key},
		fields=["journal_entry"],
		limit=1,
	)
	if rows and rows[0].journal_entry:
		return rows[0].journal_entry
	suffix = key.split("|", 1)[-1] if "|" in key else key
	rows = frappe.db.sql(
		"""
		SELECT journal_entry FROM `tabPDC Journal Reference`
		WHERE parent = %s AND (pdc_transition_key = %s OR pdc_transition_key = %s)
		ORDER BY modified DESC LIMIT 1
		""",
		(pdc_name, key, suffix),
		as_dict=True,
	)
	return (rows[0].journal_entry if rows else None) or None


def _ensure_transition_je(pdc, from_state: str, to_state: str, posting_date) -> str | None:
	je = _je_for_transition(pdc.name, from_state, to_state)
	if je:
		return je
	je = post_pdc_transition_journal_entry(pdc, from_state, to_state, posting_date=posting_date)
	if je:
		frappe.db.commit()
		pdc.reload()
	return je


def _assert_leaf_owned_by_pdc(leaf_row: dict, pdc_name: str, errors: list[str], label: str) -> None:
	if (leaf_row.get("status") or "") != "Used":
		errors.append(f"{label}: expected leaf Used, got {leaf_row.get('status')}")
	if (leaf_row.get("linked_post_dated_cheque") or "") != pdc_name:
		errors.append(f"{label}: leaf not linked to {pdc_name}")


def _workflow_save(pdc, to_state: str, t0, **fields) -> dict:
	"""Save workflow transition without bypassing cheque-leaf validate."""
	prev = normalize_workflow_state_value(pdc.workflow_state)
	to_state = normalize_workflow_state_value(to_state)
	for k, v in fields.items():
		setattr(pdc, k, v)
	pdc.workflow_state = to_state
	pdc.save(ignore_permissions=True)
	frappe.db.commit()
	pdc.reload()
	je = _ensure_transition_je(pdc, prev, to_state, t0)
	return {
		"from_state": prev,
		"to_state": to_state,
		"cheque_leaf_validation": "ok",
		"je": je,
	}


def _prepare_submitted_registered(pdc, leaf: str, t0) -> dict:
	pdc.submit()
	frappe.db.commit()
	pdc.reload()
	out = {"leaf_after_submit": _leaf_sql(leaf)}
	pdc.received_date = t0
	prev = normalize_workflow_state_value(pdc.workflow_state)
	pdc.workflow_state = WORKFLOW_REGISTERED
	pdc.save(ignore_permissions=True)
	frappe.db.commit()
	pdc.reload()
	reg_je = _ensure_transition_je(pdc, prev, WORKFLOW_REGISTERED, t0)
	out["register_je"] = reg_je
	out["leaf_at_registered"] = _leaf_sql(leaf)
	return out


def _run_through_issued(ctx: dict, leaf: str) -> tuple[frappe.model.document.Document, dict]:
	cheque_no = _cheque_no_for_leaf(leaf)
	t0 = _today()
	pdc = _new_payable_pdc(ctx, cheque_no, leaf)
	prep = _prepare_submitted_registered(pdc, leaf, t0)
	tr = _workflow_save(pdc, WORKFLOW_ISSUED, t0, handover_date=t0)
	prep["issued_transition"] = tr
	prep["leaf_after_issued"] = _leaf_sql(leaf)
	return pdc, prep


def run():
	frappe.set_user("Administrator")
	errors: list[str] = []
	scenarios: list[dict] = []
	t0 = _today()

	company = frappe.db.get_value("Company", {"name": ("!=", "")}, "name", order_by="creation asc")
	supplier = frappe.db.get_value("Supplier", {"disabled": 0}, "name", order_by="modified desc")
	bank_account = frappe.db.get_value(
		"Bank Account",
		{"company": company, "disabled": 0, "is_company_account": 1},
		"name",
		order_by="modified desc",
	)
	if not bank_account:
		bank_account = frappe.db.get_value("Bank Account", {"company": company, "disabled": 0}, "name")
	settings = _get_pdc_settings_for_company(company)
	if not (company and supplier and bank_account and settings):
		frappe.throw("Missing master data for PDC cheque leaf E2E")

	ctx = {"company": company, "supplier": supplier, "bank_account": bank_account, "settings": settings}

	# --- Primary PDC: Registered → Issued → save-only → Cleared ---
	leaf_main = _provision_available_leaf(company, bank_account)
	leaf_before = _leaf_sql(leaf_main)
	pdc_main, prep = _run_through_issued(ctx, leaf_main)
	pdc_name = pdc_main.name

	scenarios.append(
		{
			"scenario": "1_registered_to_issued",
			"pdc": pdc_name,
			"leaf": leaf_main,
			"workflow_states_tested": [WORKFLOW_REGISTERED, WORKFLOW_ISSUED],
			"leaf_before": prep.get("leaf_at_registered"),
			"leaf_after": prep.get("leaf_after_issued"),
			"je_names": [j for j in [prep.get("register_je"), prep["issued_transition"].get("je")] if j],
			"cheque_leaf_validation": prep["issued_transition"]["cheque_leaf_validation"],
		}
	)
	_assert_leaf_owned_by_pdc(prep["leaf_after_issued"], pdc_name, errors, "scenario_1")

	leaf_after_save_only = prep.get("leaf_after_issued")

	# Scenario 4 — save-only after Issued (no workflow change)
	pdc_main.return_reason = ""
	pdc_main.handover_date = t0
	try:
		pdc_main.save(ignore_permissions=True)
		frappe.db.commit()
		pdc_main.reload()
		leaf_after_save_only = _leaf_sql(leaf_main)
		scenarios.append(
			{
				"scenario": "4_save_only_after_issued",
				"pdc": pdc_name,
				"leaf": leaf_main,
				"workflow_states_tested": [WORKFLOW_ISSUED],
				"leaf_before": prep.get("leaf_after_issued"),
				"leaf_after": leaf_after_save_only,
				"je_names": [],
				"cheque_leaf_validation": "ok",
			}
		)
		_assert_leaf_owned_by_pdc(leaf_after_save_only, pdc_name, errors, "scenario_4")
	except Exception as exc:
		errors.append(f"scenario_4 save-only: {exc}")
		scenarios.append({"scenario": "4_save_only_after_issued", "cheque_leaf_validation": f"FAILED: {exc}"})

	# Scenario 2 — Issued → Cleared
	try:
		tr_clear = _workflow_save(pdc_main, WORKFLOW_CLEARED, t0, cleared_date=t0)
		leaf_after_clear = _leaf_sql(leaf_main)
		clear_je = tr_clear.get("je")
		if clear_je:
			je_doc = frappe.get_doc("Journal Entry", clear_je)
			if je_doc.docstatus != 1:
				errors.append(f"scenario_2 clear JE not submitted: {clear_je}")
		else:
			errors.append("scenario_2: expected clear JE for Issued → Cleared")
		scenarios.append(
			{
				"scenario": "2_issued_to_cleared",
				"pdc": pdc_name,
				"leaf": leaf_main,
				"workflow_states_tested": [WORKFLOW_ISSUED, WORKFLOW_CLEARED],
				"leaf_before": leaf_after_save_only,
				"leaf_after": leaf_after_clear,
				"je_names": [clear_je] if clear_je else [],
				"cheque_leaf_validation": tr_clear["cheque_leaf_validation"],
			}
		)
		_assert_leaf_owned_by_pdc(leaf_after_clear, pdc_name, errors, "scenario_2")
	except Exception as exc:
		errors.append(f"scenario_2 Issued → Cleared: {exc}")
		scenarios.append({"scenario": "2_issued_to_cleared", "cheque_leaf_validation": f"FAILED: {exc}"})
		leaf_after_clear = _leaf_sql(leaf_main)

	# Scenario 3a — Issued → Returned (separate PDC; Cleared is terminal on main)
	leaf_ret = _provision_available_leaf(company, bank_account)
	pdc_ret, prep_ret = _run_through_issued(ctx, leaf_ret)
	try:
		tr_ret = _workflow_save(
			pdc_ret, WORKFLOW_RETURNED, t0, returned_date=t0, return_reason="E2E business return"
		)
		leaf_after_ret = _leaf_sql(leaf_ret)
		ret_je = tr_ret.get("je")
		if ret_je and frappe.db.get_value("Journal Entry", ret_je, "docstatus") != 1:
			errors.append(f"scenario_3_returned JE not submitted: {ret_je}")
		scenarios.append(
			{
				"scenario": "3_issued_to_returned",
				"pdc": pdc_ret.name,
				"leaf": leaf_ret,
				"workflow_states_tested": [WORKFLOW_ISSUED, WORKFLOW_RETURNED],
				"leaf_before": prep_ret.get("leaf_after_issued"),
				"leaf_after": leaf_after_ret,
				"je_names": [ret_je] if ret_je else [],
				"cheque_leaf_validation": tr_ret["cheque_leaf_validation"],
			}
		)
		_assert_leaf_owned_by_pdc(leaf_after_ret, pdc_ret.name, errors, "scenario_3_returned")
	except Exception as exc:
		errors.append(f"scenario_3 Issued → Returned: {exc}")
		scenarios.append({"scenario": "3_issued_to_returned", "cheque_leaf_validation": f"FAILED: {exc}"})

	# Scenario 3b — Issued → Cancelled
	leaf_can = _provision_available_leaf(company, bank_account)
	pdc_can, prep_can = _run_through_issued(ctx, leaf_can)
	try:
		tr_can = _workflow_save(pdc_can, WORKFLOW_CANCELLED, t0)
		leaf_after_can = _leaf_sql(leaf_can)
		can_je = tr_can.get("je")
		if can_je and frappe.db.get_value("Journal Entry", can_je, "docstatus") != 1:
			errors.append(f"scenario_3_cancelled JE not submitted: {can_je}")
		scenarios.append(
			{
				"scenario": "3_issued_to_cancelled",
				"pdc": pdc_can.name,
				"leaf": leaf_can,
				"workflow_states_tested": [WORKFLOW_ISSUED, WORKFLOW_CANCELLED],
				"leaf_before": prep_can.get("leaf_after_issued"),
				"leaf_after": leaf_after_can,
				"je_names": [can_je] if can_je else [],
				"cheque_leaf_validation": tr_can["cheque_leaf_validation"],
			}
		)
		_assert_leaf_owned_by_pdc(leaf_after_can, pdc_can.name, errors, "scenario_3_cancelled")
	except Exception as exc:
		errors.append(f"scenario_3 Issued → Cancelled: {exc}")
		scenarios.append({"scenario": "3_issued_to_cancelled", "cheque_leaf_validation": f"FAILED: {exc}"})

	# Scenario 5 — duplicate leaf (main PDC leaf still Used+linked)
	dup_blocked = False
	try:
		_new_payable_pdc(ctx, f"LIVE-DUP-{int(time.time())}", leaf_main)
		errors.append("scenario_5: second PDC with same Used leaf should have failed")
	except frappe.ValidationError:
		dup_blocked = True
	frappe.db.rollback()

	scenarios.append(
		{
			"scenario": "5_duplicate_leaf_blocked",
			"pdc_attempted_on_leaf_of": pdc_name,
			"leaf": leaf_main,
			"leaf_snapshot": _leaf_sql(leaf_main),
			"duplicate_blocked": dup_blocked,
		}
	)
	if not dup_blocked:
		errors.append("scenario_5: duplicate leaf not blocked")

	workflow_states_all = sorted({s for sc in scenarios for s in (sc.get("workflow_states_tested") or [])})

	result = {
		"status": "PASSED" if not errors else "FAILED",
		"errors": errors,
		"primary_pdc": pdc_name,
		"primary_leaf": leaf_main,
		"leaf_before_run": leaf_before,
		"workflow_states_tested": workflow_states_all,
		"cheque_leaf_validation_errors": "none" if not errors else errors,
		"duplicate_leaf_blocked": dup_blocked,
		"scenarios": scenarios,
	}
	print(json.dumps(result, indent=2, default=str))
	if errors:
		frappe.throw("; ".join(errors))
	return result
