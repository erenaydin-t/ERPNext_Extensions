"""Prep data for PDC workflow rollback Playwright E2E."""

from __future__ import annotations

import time
from datetime import date, timedelta

import frappe
from frappe.utils import getdate, today

from erpnext_extensions.e2e.e2e_unique import e2e_unique_tag


def _uniq(prefix: str) -> str:
	return e2e_unique_tag(prefix)


def _company() -> str:
	co = frappe.db.get_value("Company", {}, "name", order_by="creation asc")
	if not co:
		frappe.throw("No Company for E2E")
	return co


def _bank_account(company: str) -> str:
	ba = frappe.db.get_value("Bank Account", {"company": company}, "name", order_by="creation asc")
	if not ba:
		frappe.throw("No Bank Account for E2E")
	return ba


def _group_account(company: str, root_type: str) -> str:
	name = frappe.db.get_value(
		"Account",
		{"company": company, "is_group": 1, "root_type": root_type},
		"name",
		order_by="lft asc",
	)
	if not name:
		frappe.throw(f"No group Account root_type={root_type} for E2E")
	return name


def _account(company: str, parent: str, account_name: str) -> str:
	exists = frappe.db.get_value("Account", {"company": company, "account_name": account_name}, "name")
	if exists:
		return exists
	acc = frappe.new_doc("Account")
	acc.company = company
	acc.parent_account = parent
	acc.account_name = account_name
	acc.is_group = 0
	acc.insert(ignore_permissions=True)
	return acc.name


def _ensure_pdc_settings(company: str, ci_hand: str, ci_clear: str, pool: str, protested: str) -> str:
	name = frappe.db.get_value("PDC Settings", {"company": company}, "name") or company
	doc = (
		frappe.get_doc("PDC Settings", name)
		if frappe.db.exists("PDC Settings", name)
		else frappe.new_doc("PDC Settings")
	)
	doc.company = company
	doc.name = name
	doc.default_cheques_in_hand_account = ci_hand
	doc.default_cheques_in_clearing_account = ci_clear
	doc.default_payable_cheque_account = pool
	doc.default_protested_account = protested
	doc.allow_endorsement = 1
	doc.require_sayad_registration = 0
	if frappe.db.exists("PDC Settings", name):
		doc.save(ignore_permissions=True)
	else:
		doc.insert(ignore_permissions=True)
	return doc.name


def _provision_payable_leaf(company: str, bank_account: str) -> str:
	start = (int(time.time() * 1000) % 900000) + 100000
	book = frappe.new_doc("Cheque Book")
	book.company = company
	book.bank_account = bank_account
	book.generation_mode = "prefix_plus_sequence"
	book.start_number = start
	book.end_number = start
	book.number_width = 6
	book.insert(ignore_permissions=True)
	book.generate_leaves()
	leaf = frappe.db.get_value("Cheque Leaf", {"cheque_book": book.name, "status": "Available"}, "name")
	if not leaf:
		frappe.throw("Failed to provision payable Cheque Leaf")
	return leaf


def _drawer_bank() -> str:
	name = frappe.db.get_value("Bank", {}, "name", order_by="creation asc")
	if name:
		return name
	bank = frappe.new_doc("Bank")
	bank.bank_name = _uniq("E2E-BANK")
	bank.insert(ignore_permissions=True)
	return bank.name


def _leaf_customer_group() -> str:
	name = frappe.db.get_value(
		"Customer Group",
		{"is_group": 0},
		"name",
		order_by="lft asc",
	)
	return name or "All Customer Groups"


def _leaf_territory() -> str:
	name = frappe.db.get_value("Territory", {"is_group": 0}, "name", order_by="lft asc")
	return name or "All Territories"


def _get_non_privileged_user() -> str:
	"""User without System Manager; password set to E2E default for Playwright login."""
	from frappe.utils.password import update_password

	password = (frappe.conf.get("e2e_test_password") or "admin").strip()
	rows = frappe.db.sql(
		"""
		SELECT u.name
		  FROM `tabUser` u
		 WHERE u.enabled = 1
		   AND u.user_type = 'System User'
		   AND u.name NOT IN ('Administrator', 'Guest')
		   AND NOT EXISTS (
		     SELECT 1 FROM `tabHas Role` hr
		      WHERE hr.parent = u.name AND hr.role = 'System Manager'
		   )
		 ORDER BY u.creation ASC
		 LIMIT 1
		""",
		as_list=True,
	)
	if not rows:
		frappe.throw("No non–System Manager user found for E2E permission test.")
	name = rows[0][0]
	update_password(name, password)
	frappe.db.commit()
	return name


def _apply_action(doc, action: str):
	from frappe.model.workflow import apply_workflow

	return apply_workflow(doc, action)


def _sync_payable_outcome_dates(doc) -> None:
	"""E2E prep: satisfy handover / cleared date sequence validations."""
	rec = getdate(doc.get("received_date") or today())
	hand = doc.get("handover_date")
	if not hand or getdate(hand) < rec:
		doc.handover_date = rec
	hand = getdate(doc.handover_date or rec)
	clr = doc.get("cleared_date")
	if clr and getdate(clr) < hand:
		doc.cleared_date = hand


def _issue_payable(doc):
	_sync_payable_outcome_dates(doc)
	doc.save(ignore_permissions=True)
	return _apply_action(doc, "Issue Cheque")


def _clear_payable(doc):
	_sync_payable_outcome_dates(doc)
	hand = getdate(doc.handover_date or doc.received_date or today())
	doc.cleared_date = max(getdate(today()), hand)
	doc.save(ignore_permissions=True)
	return _apply_action(doc, "Clear Cheque")


def _return_payable(doc):
	dirty = False
	if not doc.get("returned_date"):
		doc.returned_date = date.today()
		dirty = True
	if not doc.get("return_reason"):
		doc.return_reason = "E2E return"
		dirty = True
	if dirty:
		doc.save(ignore_permissions=True)
	return _apply_action(doc, "Return to Payee")


def _legacy_cancelled_issued_payable(doc):
	"""Legacy Cancelled fixture (docstatus=2) without removed workflow Cancel actions."""
	from erpnext_extensions.cheque_management.pdc_workflow_to_cheque_status import (
		map_workflow_state_to_cheque_status,
	)

	if doc.docstatus != 1:
		frappe.throw("Expected submitted Payable PDC before legacy cancel fixture")
	status = map_workflow_state_to_cheque_status("Payable", "Cancelled")
	frappe.db.set_value(
		"Post Dated Cheque",
		doc.name,
		{"workflow_state": "Cancelled", "cheque_status": status},
		update_modified=False,
	)
	doc = frappe.get_doc("Post Dated Cheque", doc.name)
	doc.flags.ignore_validate = True
	from erpnext_extensions.cheque_management.pdc_direct_cancel_policy import (
		pdc_internal_direct_cancel,
	)

	with pdc_internal_direct_cancel(flag="allow_pdc_direct_cancel"):
		doc.cancel()
	return doc


def _opening_import_payable_at_registered(company, bank_account, supplier, cheque_tag: str) -> str:
	from erpnext_extensions.cheque_management.doctype.cheque_opening_import.cheque_opening_import import (
		import_row,
	)
	from erpnext_extensions.cheque_management.doctype.cheque_opening_import.run_live_opening_import_accounting_e2e import (
		_base_payable_row,
	)
	from erpnext_extensions.cheque_management.run_live_party_orchestration_e2e import (
		_site_context,
	)

	ctx = _site_context()
	ctx["company"] = company
	ctx["bank_account"] = bank_account
	ctx["supplier"] = supplier
	chq = _uniq(cheque_tag)
	row = _base_payable_row(ctx, chq, "Registered")
	coi = frappe.new_doc("Cheque Opening Import")
	coi.insert(ignore_permissions=True)
	frappe.flags.cheque_opening_import_name = coi.name
	try:
		return import_row(1, row)
	finally:
		if hasattr(frappe.flags, "cheque_opening_import_name"):
			delattr(frappe.flags, "cheque_opening_import_name")


def _opening_import_payable_at(company, bank_account, supplier, cheque_tag: str, workflow_state: str) -> str:
	from erpnext_extensions.cheque_management.doctype.cheque_opening_import.cheque_opening_import import (
		import_row,
	)
	from erpnext_extensions.cheque_management.doctype.cheque_opening_import.run_live_opening_import_accounting_e2e import (
		_base_payable_row,
	)
	from erpnext_extensions.cheque_management.run_live_party_orchestration_e2e import (
		_site_context,
	)

	ctx = _site_context()
	ctx["company"] = company
	ctx["bank_account"] = bank_account
	ctx["supplier"] = supplier
	chq = _uniq(cheque_tag)
	row = _base_payable_row(ctx, chq, workflow_state)
	if workflow_state == "Issued":
		row["handover_date"] = today()
	if workflow_state == "Cleared":
		row["handover_date"] = today()
		row["cleared_date"] = today()
	coi = frappe.new_doc("Cheque Opening Import")
	coi.insert(ignore_permissions=True)
	frappe.flags.cheque_opening_import_name = coi.name
	try:
		return import_row(1, row)
	finally:
		if hasattr(frappe.flags, "cheque_opening_import_name"):
			delattr(frappe.flags, "cheque_opening_import_name")


def _make_payable_pdc(company, bank_account, supplier, pool, ap) -> "PostDatedCheque":
	leaf = _provision_payable_leaf(company, bank_account)
	cheque_no = frappe.db.get_value("Cheque Leaf", leaf, "cheque_number")
	pdc = frappe.new_doc("Post Dated Cheque")
	pdc.naming_series = "PDC-.YYYY.-"
	pdc.company = company
	pdc.cheque_direction = "Payable"
	pdc.allocation_mode = "direct_settlement"
	pdc.advance_scope = "order_based"
	pdc.party_type = "Supplier"
	pdc.party = supplier
	pdc.cheque_no = cheque_no
	pdc.cheque_due_date = date.today() + timedelta(days=30)
	pdc.received_date = date.today()
	pdc.cheque_amount = 1000
	pdc.bank_account = bank_account
	pdc.cheque_leaf = leaf
	pdc.account_paid_from = pool
	pdc.account_paid_to = ap
	pdc.insert(ignore_permissions=True)
	return pdc


def prepare_pdc_workflow_rollback_e2e():
	frappe.set_user("Administrator")

	company = _company()
	bank_account = _bank_account(company)
	assets = _group_account(company, "Asset")
	liab = _group_account(company, "Liability")

	ci_hand = _account(company, assets, _uniq("E2E-CIH"))
	ci_clear = _account(company, assets, _uniq("E2E-CLR"))
	protested = _account(company, assets, _uniq("E2E-PROT"))
	pool = _account(company, liab, _uniq("E2E-POOL"))
	ap = _account(company, liab, _uniq("E2E-AP"))
	ar = _account(company, assets, _uniq("E2E-AR"))

	_ensure_pdc_settings(company, ci_hand, ci_clear, pool, protested)

	accounts_user = _get_non_privileged_user()

	# Payable PDC for A/B/C/D/E/F/J/K
	supplier = frappe.get_doc(
		{
			"doctype": "Supplier",
			"supplier_name": _uniq("SUP-E2E"),
			"supplier_type": "Individual",
			"supplier_group": frappe.db.get_value("Supplier Group", {}, "name", order_by="lft asc")
			or "All Supplier Groups",
		}
	).insert(ignore_permissions=True)
	frappe.db.commit()

	pdc_payable = _make_payable_pdc(company, bank_account, supplier.name, pool, ap)

	# Move to Registered for scenario A baseline
	pdc_registered = _apply_action(pdc_payable, "Register Cheque")

	pdc_payable2 = _make_payable_pdc(company, bank_account, supplier.name, pool, ap)
	pdc_payable2 = _apply_action(pdc_payable2, "Register Cheque")
	pdc_payable2 = _issue_payable(pdc_payable2)
	pdc_payable2 = _clear_payable(pdc_payable2)

	pdc_payable3 = _make_payable_pdc(company, bank_account, supplier.name, pool, ap)
	pdc_payable3 = _apply_action(pdc_payable3, "Register Cheque")
	pdc_payable3 = _issue_payable(pdc_payable3)
	pdc_payable3 = _return_payable(pdc_payable3)

	pdc_payable4 = _make_payable_pdc(company, bank_account, supplier.name, pool, ap)
	pdc_payable4 = _apply_action(pdc_payable4, "Register Cheque")
	pdc_payable4 = _issue_payable(pdc_payable4)
	pdc_payable4 = _legacy_cancelled_issued_payable(pdc_payable4)

	pdc_payable_b = _make_payable_pdc(company, bank_account, supplier.name, pool, ap)
	pdc_payable_b = _apply_action(pdc_payable_b, "Register Cheque")
	pdc_payable_b = _issue_payable(pdc_payable_b)

	pdc_payable_h = _make_payable_pdc(company, bank_account, supplier.name, pool, ap)
	pdc_payable_h = _apply_action(pdc_payable_h, "Register Cheque")
	pdc_payable_h = _issue_payable(pdc_payable_h)
	pdc_payable_h = _clear_payable(pdc_payable_h)

	pdc_payable_j = _make_payable_pdc(company, bank_account, supplier.name, pool, ap)
	pdc_payable_j = _apply_action(pdc_payable_j, "Register Cheque")
	pdc_payable_j = _issue_payable(pdc_payable_j)
	pdc_payable_j = _clear_payable(pdc_payable_j)

	frappe.db.commit()

	# Receivable PDC for receivable scenarios
	customer = frappe.get_doc(
		{
			"doctype": "Customer",
			"customer_name": _uniq("CUST-E2E"),
			"customer_type": "Individual",
			"customer_group": _leaf_customer_group(),
			"territory": _leaf_territory(),
		}
	).insert(ignore_permissions=True)
	pdc_recv = frappe.new_doc("Post Dated Cheque")
	pdc_recv.naming_series = "PDC-.YYYY.-"
	pdc_recv.company = company
	pdc_recv.cheque_direction = "Receivable"
	pdc_recv.allocation_mode = "direct_settlement"
	pdc_recv.advance_scope = "order_based"
	pdc_recv.party_type = "Customer"
	pdc_recv.party = customer.name
	pdc_recv.cheque_no = str(int(time.time()) % 900000 + 200000)
	pdc_recv.cheque_due_date = date.today() + timedelta(days=30)
	pdc_recv.received_date = date.today()
	pdc_recv.cheque_amount = 1200
	pdc_recv.bank_account = bank_account
	pdc_recv.drawer_bank_name = _drawer_bank()
	pdc_recv.account_paid_from = ar
	pdc_recv.insert(ignore_permissions=True)
	pdc_recv = _apply_action(pdc_recv, "Register Cheque")
	if not pdc_recv.get("sent_to_bank_date"):
		pdc_recv.sent_to_bank_date = date.today()
		pdc_recv.save(ignore_permissions=True)
	pdc_recv = _apply_action(pdc_recv, "Send to Bank")
	if not pdc_recv.get("cleared_date"):
		pdc_recv.cleared_date = date.today()
		pdc_recv.save(ignore_permissions=True)
	pdc_recv = _apply_action(pdc_recv, "Clear Cheque")

	opening_import_registered = _opening_import_payable_at_registered(
		company, bank_account, supplier.name, _uniq("E2E-OI-RB-REG")
	)
	opening_import_issued_baseline = _opening_import_payable_at(
		company, bank_account, supplier.name, _uniq("E2E-OI-PAY-ISSUED-B"), "Issued"
	)
	opening_import_issued = _opening_import_payable_at(
		company, bank_account, supplier.name, _uniq("E2E-OI-PAY-ISSUED"), "Issued"
	)
	opening_import_cleared_baseline = _opening_import_payable_at(
		company, bank_account, supplier.name, _uniq("E2E-OI-PAY-CLEARED"), "Cleared"
	)
	frappe.db.commit()
	opening_import_cleared = _opening_import_payable_at_registered(
		company, bank_account, supplier.name, _uniq("E2E-OI-RB-CLR")
	)
	frappe.db.commit()
	oi_doc = frappe.get_doc("Post Dated Cheque", opening_import_cleared)
	oi_doc = _issue_payable(oi_doc)
	oi_doc = _clear_payable(oi_doc)

	oi_issued_doc = frappe.get_doc("Post Dated Cheque", opening_import_issued)
	oi_issued_doc = _clear_payable(oi_issued_doc)

	frappe.db.commit()

	return {
		"company": company,
		"bank_account": bank_account,
		"accounts_user": accounts_user,
		"accounts_user_password_hint": "admin (or site e2e_test_password)",
		"payable_registered": pdc_registered.name,
		"payable_issued": pdc_payable_b.name,
		"payable_cleared": pdc_payable2.name,
		"payable_cleared_preview": pdc_payable_h.name,
		"payable_cleared_double": pdc_payable_j.name,
		"payable_returned": pdc_payable3.name,
		"payable_cancelled": pdc_payable4.name,
		"receivable_cleared": pdc_recv.name,
		"opening_import_payable_registered": opening_import_registered,
		"opening_import_payable_issued_baseline": opening_import_issued_baseline,
		"opening_import_payable_issued": oi_issued_doc.name,
		"opening_import_payable_cleared_baseline": opening_import_cleared_baseline,
		"opening_import_payable_cleared": oi_doc.name,
	}


def e2e_get_rollback_targets(pdc_name: str) -> dict:
	from erpnext_extensions.cheque_management.pdc_workflow_rollback import get_rollback_target_states

	return {"targets": get_rollback_target_states(pdc_name)}


def e2e_get_pdc_state(pdc_name: str) -> dict:
	"""Bench execute helper: PDC row from DB (delegates to shared e2e_document_state)."""
	from erpnext_extensions.e2e.e2e_document_state import e2e_get_document_state

	return e2e_get_document_state(
		"Post Dated Cheque",
		pdc_name,
		["name", "workflow_state", "cheque_status", "docstatus"],
	)


def e2e_sql_verify_pdc(pdc_name: str):
	"""Bench execute helper for Playwright SQL checks."""
	from erpnext_extensions.cheque_management.pdc_rollback_sql_evidence import (
		accounting_snapshot_for_pdc,
	)
	from erpnext_extensions.cheque_management.pdc_workflow_rollback import (
		sql_integrity_is_clean,
		sql_verify_pdc_rollback_integrity,
	)

	report = sql_verify_pdc_rollback_integrity(pdc_name)
	snapshot = accounting_snapshot_for_pdc(pdc_name)
	return {
		"pdc_name": pdc_name,
		"report": report,
		"clean": sql_integrity_is_clean(report),
		"snapshot": snapshot,
	}


def e2e_attempt_direct_cancel(pdc_name: str) -> dict:
	"""Try doc.cancel(); verify block + unchanged docstatus/workflow_state."""
	before = frappe.db.get_value(
		"Post Dated Cheque",
		pdc_name,
		["docstatus", "workflow_state"],
		as_dict=True,
	)
	frappe.db.savepoint("e2e_pdc_direct_cancel_attempt")
	try:
		frappe.get_doc("Post Dated Cheque", pdc_name).cancel()
		frappe.db.rollback(save_point="e2e_pdc_direct_cancel_attempt")
		after = frappe.db.get_value(
			"Post Dated Cheque",
			pdc_name,
			["docstatus", "workflow_state"],
			as_dict=True,
		)
		return {"blocked": False, "before": before, "after": after}
	except Exception as e:
		frappe.db.rollback(save_point="e2e_pdc_direct_cancel_attempt")
		after = frappe.db.get_value(
			"Post Dated Cheque",
			pdc_name,
			["docstatus", "workflow_state"],
			as_dict=True,
		)
		return {
			"blocked": True,
			"message": str(e),
			"before": before,
			"after": after,
		}


def e2e_list_workflow_actions(pdc_name: str) -> list[str]:
	"""Workflow actions currently exposed on the PDC (for E2E — no Cancel actions)."""
	from frappe.model.workflow import get_transitions

	doc = frappe.get_doc("Post Dated Cheque", pdc_name)
	return sorted({t.get("action") or "" for t in get_transitions(doc) if t.get("action")})


def e2e_apply_pdc_workflow(pdc_name: str, action: str) -> str:
	from frappe.model.workflow import apply_workflow

	doc = apply_workflow(frappe.get_doc("Post Dated Cheque", pdc_name), action)
	frappe.db.commit()
	return doc.workflow_state


def e2e_forward_register_after_rollback(pdc_name: str) -> dict:
	"""Scenario K: re-register only when PDC is in Draft after rollback."""
	doc = frappe.get_doc("Post Dated Cheque", pdc_name)
	if doc.workflow_state != "Draft":
		return {"ok": False, "workflow_state": doc.workflow_state, "reason": "not_draft"}
	state = e2e_apply_pdc_workflow(pdc_name, "Register Cheque")
	return {"ok": state == "Registered", "workflow_state": state}
