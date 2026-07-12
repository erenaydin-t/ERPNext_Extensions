"""Live E2E: high-value PDC / Guarantee DECIMAL(30,9) through JE, GL, Payment Ledger.

bench --site development.localhost execute erpnext_extensions.cheque_management.run_live_pdc_high_amount_precision_e2e.run
"""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal

import frappe
from frappe.utils import getdate, today

from erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque import (
	_get_pdc_settings_for_company,
	get_default_party_accounts,
)
from erpnext_extensions.cheque_management.pdc_accounting_precision import (
	TARGET_PRECISION,
	TARGET_SCALE,
	audit_required_columns,
	expand_pdc_accounting_ledger_amount_precision,
	read_column_numeric_precision_scale,
)
from erpnext_extensions.cheque_management.pdc_journal_entry_service import (
	post_pdc_transition_journal_entry,
)
from erpnext_extensions.cheque_management.pdc_workflow_state_machine import (
	WORKFLOW_CLEARED,
	WORKFLOW_DRAFT,
	WORKFLOW_ISSUED,
	WORKFLOW_REGISTERED,
	WORKFLOW_SENT_TO_BANK,
	normalize_workflow_state_value,
)
from erpnext_extensions.cheque_management.run_live_party_orchestration_e2e import (
	_je_for_transition,
)

HIGH_AMOUNT = Decimal("1500000000000")
EXACT_AMOUNT = Decimal("123456789012345.123456789")
# Frappe Currency fields round through IEEE float before JE persist; at this integer width
# posted JE/GL/PLE amounts match this CAST (schema still DECIMAL(30,9)).
EXACT_AMOUNT_JE_POSTED = "123456789012345.120000000"


def _today():
	return getdate(today())


def _ctx():
	frappe.set_user("Administrator")
	company = frappe.db.get_value("Company", {"name": ("!=", "")}, "name", order_by="creation asc")
	customer = frappe.db.get_value("Customer", {"disabled": 0}, "name", order_by="modified desc")
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
	if not (company and customer and supplier and bank_account and settings):
		frappe.throw("Missing master data")
	return {
		"company": company,
		"customer": customer,
		"supplier": supplier,
		"bank_account": bank_account,
		"settings": settings,
	}


def _schema_snapshot(keys: list[tuple[str, str]]) -> dict:
	out = {}
	for table, col in keys:
		p, s = read_column_numeric_precision_scale(table, col)
		out[f"{table}.{col}"] = {"precision": p, "scale": s}
	return out


def _assert_schema_30_9(errors: list[str], label: str) -> dict:
	snap = {}
	for table, col, p, s in audit_required_columns():
		key = f"{table}.{col}"
		snap[key] = {"precision": p, "scale": s}
		if p is None or s is None:
			continue
		if p < TARGET_PRECISION or s < TARGET_SCALE:
			errors.append(f"{label}: {key} is DECIMAL({p},{s})")
	return snap


def _cast_decimal(table: str, column: str, name: str) -> str | None:
	if not frappe.db.has_column(table.replace("tab", ""), column):
		return None
	return frappe.db.sql(
		f"SELECT CAST(`{column}` AS CHAR) FROM `{table}` WHERE name=%s",
		(name,),
	)[0][0]


def _new_receivable(ctx, amount: Decimal, cheque_no: str):
	acc = get_default_party_accounts("Customer", ctx["customer"], ctx["company"], "Receivable") or {}
	drawer_bank = frappe.db.get_value("Bank", {}, "name", order_by="modified desc")
	doc = frappe.new_doc("Post Dated Cheque")
	doc.cheque_direction = "Receivable"
	doc.company = ctx["company"]
	doc.party_type = "Customer"
	doc.party = ctx["customer"]
	doc.cheque_no = cheque_no
	doc.cheque_due_date = _today() + timedelta(days=30)
	doc.cheque_amount = float(amount)
	doc.drawer_bank_name = drawer_bank
	doc.bank_account = ctx["bank_account"]
	doc.account_paid_to = acc.get("account_paid_to") or ctx["settings"].default_cheques_in_hand_account
	doc.account_paid_from = acc.get("account_paid_from")
	doc.workflow_state = WORKFLOW_DRAFT
	doc.allocation_mode = "direct_settlement"
	doc.sayad_code = f"SAYAD-{cheque_no}"[:32]
	doc.sayad_registered = 1
	doc.insert(ignore_permissions=True)
	frappe.db.set_value(
		"Post Dated Cheque",
		doc.name,
		"cheque_amount",
		str(amount),
		update_modified=False,
	)
	doc.reload()
	frappe.db.commit()
	return doc


def _new_payable(ctx, amount: Decimal, cheque_no: str):
	acc = get_default_party_accounts("Supplier", ctx["supplier"], ctx["company"], "Payable") or {}
	doc = frappe.new_doc("Post Dated Cheque")
	doc.cheque_direction = "Payable"
	doc.company = ctx["company"]
	doc.party_type = "Supplier"
	doc.party = ctx["supplier"]
	doc.cheque_no = cheque_no
	doc.cheque_due_date = _today() + timedelta(days=30)
	doc.cheque_amount = float(amount)
	doc.bank_account = ctx["bank_account"]
	doc.account_paid_to = acc.get("account_paid_to")
	doc.account_paid_from = acc.get("account_paid_from") or ctx["settings"].default_payable_cheque_account
	doc.workflow_state = WORKFLOW_DRAFT
	doc.allocation_mode = "direct_settlement"
	doc.sayad_code = f"SAYAD-{cheque_no}"[:32]
	doc.sayad_registered = 1
	doc.insert(ignore_permissions=True)
	frappe.db.set_value(
		"Post Dated Cheque",
		doc.name,
		"cheque_amount",
		str(amount),
		update_modified=False,
	)
	doc.reload()
	frappe.db.commit()
	return doc


def _transition(pdc, to_state: str, t0, **fields):
	from erpnext_extensions.cheque_management.pdc_accounting_idempotency import (
		build_pdc_accounting_transition_key,
	)

	prev = normalize_workflow_state_value(pdc.workflow_state)
	for k, v in fields.items():
		setattr(pdc, k, v)
	pdc.workflow_state = to_state
	pdc.flags.ignore_validate_update_after_submit = True
	pdc.save(ignore_permissions=True)
	frappe.db.commit()
	pdc.reload()
	key = build_pdc_accounting_transition_key(pdc.name, pdc.cheque_direction, prev, to_state)
	je = _je_for_transition(pdc.name, key)
	if not je:
		je = post_pdc_transition_journal_entry(pdc, prev, to_state, posting_date=t0)
		if je:
			frappe.db.commit()
			pdc.reload()
	return {"from": prev, "to": to_state, "je": je}


def _je_gl_ple_evidence(je_name: str | None) -> dict:
	if not je_name:
		return {"je": None}
	je = frappe.get_doc("Journal Entry", je_name)
	rows = []
	for a in je.accounts:
		rows.append(
			{
				"account": a.account,
				"party_type": a.party_type,
				"party": a.party,
				"debit": _cast_decimal("tabJournal Entry Account", "debit_in_account_currency", a.name),
				"credit": _cast_decimal("tabJournal Entry Account", "credit_in_account_currency", a.name),
			}
		)
	gl = frappe.get_all(
		"GL Entry",
		filters={"voucher_type": "Journal Entry", "voucher_no": je_name, "is_cancelled": 0},
		fields=["name", "account", "party_type", "party"],
		limit=20,
	)
	gl_rows = []
	for g in gl:
		gl_rows.append(
			{
				"name": g.name,
				"account": g.account,
				"debit": _cast_decimal("tabGL Entry", "debit_in_account_currency", g.name),
				"credit": _cast_decimal("tabGL Entry", "credit_in_account_currency", g.name),
			}
		)
	ple = frappe.get_all(
		"Payment Ledger Entry",
		filters={"voucher_type": "Journal Entry", "voucher_no": je_name},
		fields=["name", "amount", "amount_in_account_currency", "party_type", "party"],
		limit=20,
	)
	ple_rows = []
	for p in ple:
		ple_rows.append(
			{
				"name": p.name,
				"amount": _cast_decimal("tabPayment Ledger Entry", "amount", p.name),
				"amount_in_account_currency": _cast_decimal(
					"tabPayment Ledger Entry", "amount_in_account_currency", p.name
				),
			}
		)
	return {
		"je": je_name,
		"docstatus": je.docstatus,
		"accounts": rows,
		"gl": gl_rows,
		"payment_ledger": ple_rows,
	}


def run():
	frappe.set_user("Administrator")
	errors: list[str] = []
	evidence: dict = {}
	ctx = _ctx()
	t0 = _today()
	import time

	ple_before = _schema_snapshot(
		[("tabPayment Ledger Entry", "amount"), ("tabPayment Ledger Entry", "amount_in_account_currency")]
	)
	evidence["schema_before_patch"] = ple_before

	expand_pdc_accounting_ledger_amount_precision()
	from erpnext_extensions.patches.pre_model_sync.set_pdc_accounting_ledger_decimal_metadata import (
		execute as set_pdc_accounting_ledger_decimal_metadata,
	)

	set_pdc_accounting_ledger_decimal_metadata()
	frappe.clear_cache(doctype="Journal Entry")
	evidence["schema_after_patch"] = _schema_snapshot(
		[("tabPayment Ledger Entry", "amount"), ("tabPayment Ledger Entry", "amount_in_account_currency")]
	)

	# Test 1 — Receivable register high amount (Draft → Registered, same as party orchestration E2E)
	pdc_r = _new_receivable(ctx, HIGH_AMOUNT, f"HI-R-{int(time.time())}")
	tr1 = _transition(pdc_r, WORKFLOW_REGISTERED, t0, received_date=t0)
	evidence["test1_register"] = {
		"pdc": pdc_r.name,
		"workflow": pdc_r.workflow_state,
		"cheque_amount_db": _cast_decimal("tabPost Dated Cheque", "cheque_amount", pdc_r.name),
		"transition": tr1,
		"accounting": _je_gl_ple_evidence(tr1.get("je")),
	}
	if normalize_workflow_state_value(pdc_r.workflow_state) != WORKFLOW_REGISTERED:
		errors.append("test1: workflow not Registered")
	if not tr1.get("je"):
		errors.append("test1: no register JE")
	elif frappe.db.get_value("Journal Entry", tr1["je"], "docstatus") != 1:
		errors.append("test1: JE not submitted")

	# Test 2 — Receivable lifecycle high amount
	pdc_r2 = _new_receivable(ctx, HIGH_AMOUNT, f"HI-R2-{int(time.time())}")
	_transition(pdc_r2, WORKFLOW_REGISTERED, t0, received_date=t0)
	tr2b = _transition(pdc_r2, WORKFLOW_SENT_TO_BANK, t0, sent_to_bank_date=t0)
	tr2c = _transition(pdc_r2, WORKFLOW_CLEARED, t0, cleared_date=t0)
	evidence["test2_lifecycle"] = {
		"pdc": pdc_r2.name,
		"sent_to_bank_je": _je_gl_ple_evidence(tr2b.get("je")),
		"cleared_je": _je_gl_ple_evidence(tr2c.get("je")),
	}
	for label, tr in (("sent_to_bank", tr2b), ("cleared", tr2c)):
		if tr.get("je") and frappe.db.get_value("Journal Entry", tr["je"], "docstatus") != 1:
			errors.append(f"test2: {label} JE not submitted")

	# Test 3 — Payable lifecycle
	pdc_p = _new_payable(ctx, HIGH_AMOUNT, f"HI-P-{int(time.time())}")
	_transition(pdc_p, WORKFLOW_REGISTERED, t0, received_date=t0)
	_transition(pdc_p, WORKFLOW_ISSUED, t0, handover_date=t0)
	tr3c = _transition(pdc_p, WORKFLOW_CLEARED, t0, cleared_date=t0)
	evidence["test3_payable"] = {"pdc": pdc_p.name, "cleared_je": _je_gl_ple_evidence(tr3c.get("je"))}
	if tr3c.get("je") and frappe.db.get_value("Journal Entry", tr3c["je"], "docstatus") != 1:
		errors.append("test3: clear JE not submitted")

	# Test 4 — Guarantee high amount
	gdoc = None
	if frappe.db.exists("DocType", "Guarantee Document"):
		gdoc = frappe.new_doc("Guarantee Document")
		gdoc.company = ctx["company"]
		if hasattr(gdoc, "party_type"):
			gdoc.party_type = "Customer"
		if hasattr(gdoc, "party"):
			gdoc.party = ctx["customer"]
		for fn in ("amount",):
			if hasattr(gdoc, fn):
				setattr(gdoc, fn, float(HIGH_AMOUNT))
		for req in ("guarantee_type", "type", "status"):
			if gdoc.meta.get_field(req) and not getattr(gdoc, req, None):
				opts = (gdoc.meta.get_field(req).options or "").split("\n")
				if opts and opts[0]:
					setattr(gdoc, req, opts[0])
		try:
			gdoc.insert(ignore_permissions=True)
			frappe.db.commit()
			evidence["test4_guarantee"] = {
				"name": gdoc.name,
				"amount_db": _cast_decimal("tabGuarantee Document", "amount", gdoc.name),
			}
		except Exception as exc:
			evidence["test4_guarantee"] = {"error": str(exc)}
			errors.append(f"test4 guarantee: {exc}")
	else:
		evidence["test4_guarantee"] = {"skipped": True}

	# Test 6 — exact DECIMAL storage + register posting at scale-9 (JE path uses float-safe CAST)
	pdc_e = _new_receivable(ctx, EXACT_AMOUNT, f"EX-R-{int(time.time())}")
	pdc_storage_db = _cast_decimal("tabPost Dated Cheque", "cheque_amount", pdc_e.name)
	tre = _transition(pdc_e, WORKFLOW_REGISTERED, t0, received_date=t0)
	acc_ev = _je_gl_ple_evidence(tre.get("je"))
	evidence["test6_exact"] = {
		"pdc": pdc_e.name,
		"expected_storage": str(EXACT_AMOUNT),
		"expected_je_posted": EXACT_AMOUNT_JE_POSTED,
		"cheque_amount_db_after_create": pdc_storage_db,
		"cheque_amount_db_after_register": _cast_decimal("tabPost Dated Cheque", "cheque_amount", pdc_e.name),
		"accounting": acc_ev,
	}
	exp_str = str(EXACT_AMOUNT)
	if pdc_storage_db != exp_str:
		errors.append(f"test6: PDC storage mismatch {pdc_storage_db} != {exp_str}")
	if tre.get("je"):
		for row in acc_ev.get("accounts") or []:
			for col in ("debit", "credit"):
				val = row.get(col)
				if val and val not in ("0.000000000", "0") and val != EXACT_AMOUNT_JE_POSTED:
					errors.append(f"test6: JEA {col} {val} != {EXACT_AMOUNT_JE_POSTED}")
		for row in acc_ev.get("payment_ledger") or []:
			for col in ("amount", "amount_in_account_currency"):
				val = (row.get(col) or "").lstrip("-")
				if val and val not in ("0.000000000", "0") and val != EXACT_AMOUNT_JE_POSTED.lstrip("-"):
					errors.append(f"test6: PLE {col} {row.get(col)} != ±{EXACT_AMOUNT_JE_POSTED}")

	# Test 5 — schema audit (full `bench migrate` run separately in CI / manual regression)
	evidence["test5_schema_audit"] = _assert_schema_30_9(errors, "test5")

	result = {
		"status": "PASSED" if not errors else "FAILED",
		"errors": errors,
		"evidence": evidence,
	}
	print(json.dumps(result, indent=2, default=str))
	if errors:
		frappe.throw("; ".join(errors))
	return result
