"""Live orchestration E2E: party on both JE sides (development.localhost).

bench --site development.localhost execute erpnext_extensions.cheque_management.run_live_party_orchestration_e2e.run
"""

from __future__ import annotations

import json
import time
from datetime import date, timedelta
from unittest.mock import patch

import frappe
from frappe.utils import getdate, today

from erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque import (
	_get_pdc_settings_for_company,
	_pdc_bank_gl_account,
	get_default_party_accounts,
)
from erpnext_extensions.cheque_management.pdc_accounting_idempotency import (
	build_pdc_accounting_transition_key,
)
from erpnext_extensions.cheque_management.pdc_workflow_state_machine import (
	WORKFLOW_BOUNCED,
	WORKFLOW_CLEARED,
	WORKFLOW_DRAFT,
	WORKFLOW_ENDORSED,
	WORKFLOW_ISSUED,
	WORKFLOW_REGISTERED,
	WORKFLOW_SENT_TO_BANK,
	normalize_workflow_state_value,
)


def _today():
	return getdate(today())


def _site_context():
	frappe.set_user("Administrator")
	company = frappe.db.get_value("Company", {"name": ("!=", "")}, "name", order_by="creation asc")
	if not company:
		frappe.throw("No Company")
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
	if not (customer and supplier and bank_account):
		frappe.throw(
			f"Missing master data company={company} customer={customer} supplier={supplier} bank={bank_account}"
		)
	settings = _get_pdc_settings_for_company(company)
	if not settings:
		frappe.throw(f"PDC Settings missing for {company}")
	bank_gl = frappe.db.get_value("Bank Account", bank_account, "account")
	return {
		"company": company,
		"customer": customer,
		"supplier": supplier,
		"bank_account": bank_account,
		"bank_gl": bank_gl,
		"settings": settings,
	}


def _unique_cheque_no(prefix: str) -> str:
	return f"{prefix}-{int(time.time())}"


def _new_receivable_pdc(ctx: dict, cheque_no: str) -> frappe.model.document.Document:
	acc = get_default_party_accounts("Customer", ctx["customer"], ctx["company"], "Receivable") or {}
	doc = frappe.new_doc("Post Dated Cheque")
	doc.cheque_direction = "Receivable"
	doc.company = ctx["company"]
	doc.party_type = "Customer"
	doc.party = ctx["customer"]
	doc.cheque_no = cheque_no
	doc.cheque_due_date = _today() + timedelta(days=30)
	doc.cheque_amount = 100.0
	drawer_bank = frappe.db.get_value("Bank", {}, "name", order_by="modified desc")
	if not drawer_bank:
		frappe.throw("No Bank master for drawer_bank_name")
	doc.drawer_bank_name = drawer_bank
	doc.bank_account = ctx["bank_account"]
	doc.account_paid_to = acc.get("account_paid_to") or ctx["settings"].default_cheques_in_hand_account
	doc.account_paid_from = acc.get("account_paid_from")
	doc.workflow_state = WORKFLOW_DRAFT
	doc.allocation_mode = "direct_settlement"
	doc.sayad_code = f"SAYAD-{cheque_no}"[:32]
	doc.sayad_registered = 1
	doc.insert(ignore_permissions=True)
	frappe.db.commit()
	return doc


def _new_payable_pdc(ctx: dict, cheque_no: str) -> frappe.model.document.Document:
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
	doc.account_paid_to = acc.get("account_paid_to")
	doc.account_paid_from = acc.get("account_paid_from") or ctx["settings"].default_payable_cheque_account
	doc.workflow_state = WORKFLOW_DRAFT
	doc.allocation_mode = "direct_settlement"
	doc.sayad_code = f"SAYAD-{cheque_no}"[:32]
	doc.sayad_registered = 1
	doc.insert(ignore_permissions=True)
	frappe.db.commit()
	return doc


def _transition(pdc, to_state: str, **fields):
	from erpnext_extensions.cheque_management.pdc_journal_entry_service import (
		post_pdc_transition_journal_entry,
	)

	prev = normalize_workflow_state_value(pdc.workflow_state)
	to_state = normalize_workflow_state_value(to_state)
	posting_date = None
	for k, v in fields.items():
		setattr(pdc, k, v)
		if k.endswith("_date"):
			posting_date = getdate(v)
	pdc.workflow_state = to_state
	pdc.flags.ignore_validate_update_after_submit = True
	pdc.save(ignore_permissions=True)
	frappe.db.commit()
	pdc.reload()
	key = build_pdc_accounting_transition_key(pdc.name, pdc.cheque_direction, prev, to_state)
	je_name = _je_for_transition(pdc.name, key)
	if not je_name:
		je_name = post_pdc_transition_journal_entry(
			pdc, prev, to_state, posting_date=posting_date or _today()
		)
		if je_name:
			frappe.db.commit()
			pdc.reload()
	return {"from": prev, "to": to_state, "transition_key": key, "je": je_name}


def _je_for_transition(pdc_name: str, transition_key: str) -> str | None:
	rows = frappe.get_all(
		"PDC Journal Reference",
		filters={"parent": pdc_name, "pdc_transition_key": transition_key},
		fields=["journal_entry"],
		limit=1,
	)
	if rows and rows[0].journal_entry:
		return rows[0].journal_entry
	# legacy suffix match
	suffix = transition_key.split("|", 1)[-1] if "|" in transition_key else transition_key
	rows = frappe.db.sql(
		"""
		SELECT journal_entry FROM `tabPDC Journal Reference`
		WHERE parent = %s AND (pdc_transition_key = %s OR pdc_transition_key = %s)
		ORDER BY modified DESC LIMIT 1
		""",
		(pdc_name, transition_key, suffix),
		as_dict=True,
	)
	return (rows[0].journal_entry if rows else None) or None


def _je_report(je_name: str | None, ctx: dict) -> dict:
	if not je_name:
		return {"je": None, "docstatus": None, "accounts": [], "gl": []}
	je = frappe.get_doc("Journal Entry", je_name)
	accounts = []
	for row in je.accounts:
		accounts.append(
			{
				"account": row.account,
				"party_type": row.party_type or "",
				"party": row.party or "",
				"debit": float(row.debit_in_account_currency or 0),
				"credit": float(row.credit_in_account_currency or 0),
			}
		)
	gl = frappe.get_all(
		"GL Entry",
		filters={"voucher_type": "Journal Entry", "voucher_no": je_name, "is_cancelled": 0},
		fields=["account", "party_type", "party", "debit", "credit"],
		order_by="idx asc",
	)
	return {
		"je": je_name,
		"docstatus": je.docstatus,
		"voucher_type": je.voucher_type,
		"accounts": accounts,
		"gl": gl,
		"bank_gl": ctx.get("bank_gl"),
	}


def _assert_party_policy(
	report: dict, scenario: str, expect_both: bool, expect_clear_split: bool
) -> list[str]:
	errors = []
	rows = report.get("accounts") or []
	bank_gl = report.get("bank_gl")
	if not report.get("je"):
		errors.append(f"{scenario}: no JE created")
		return errors
	if report.get("docstatus") != 1:
		errors.append(f"{scenario}: JE not submitted (docstatus={report.get('docstatus')})")
	if expect_clear_split and bank_gl:
		for r in rows:
			if r["account"] == bank_gl:
				if r.get("party_type") or r.get("party"):
					errors.append(f"{scenario}: bank line has party")
			else:
				if not r.get("party_type") or not r.get("party"):
					errors.append(f"{scenario}: non-bank line missing party")
	elif expect_both:
		for r in rows:
			if not r.get("party_type") or not r.get("party"):
				errors.append(f"{scenario}: line missing party on account {r.get('account')}")
	# GL mirrors party on rows that had party
	for gle in report.get("gl") or []:
		if gle.account == bank_gl and (gle.party_type or gle.party):
			errors.append(f"{scenario}: GL bank line has party")
	return errors


def run():
	ctx = _site_context()
	results = []
	errors = []
	t0 = _today()

	# 1 Receivable Register
	pdc_r1 = _new_receivable_pdc(ctx, _unique_cheque_no("LIVE-R-REG"))
	tr = _transition(pdc_r1, WORKFLOW_REGISTERED, received_date=t0)
	rep = _je_report(tr["je"], ctx)
	results.append({"scenario": "1_receivable_register", "pdc": pdc_r1.name, "transition": tr, "report": rep})
	errors.extend(
		_assert_party_policy(rep, "1_receivable_register", expect_both=True, expect_clear_split=False)
	)

	# 2 Receivable Send To Bank
	pdc_r2 = _new_receivable_pdc(ctx, _unique_cheque_no("LIVE-R-STB"))
	_transition(pdc_r2, WORKFLOW_REGISTERED, received_date=t0)
	tr = _transition(pdc_r2, WORKFLOW_SENT_TO_BANK, sent_to_bank_date=t0)
	rep = _je_report(tr["je"], ctx)
	results.append(
		{"scenario": "2_receivable_send_to_bank", "pdc": pdc_r2.name, "transition": tr, "report": rep}
	)
	errors.extend(
		_assert_party_policy(rep, "2_receivable_send_to_bank", expect_both=True, expect_clear_split=False)
	)

	# 3 Receivable Bounce
	pdc_r3 = _new_receivable_pdc(ctx, _unique_cheque_no("LIVE-R-BOU"))
	_transition(pdc_r3, WORKFLOW_REGISTERED, received_date=t0)
	_transition(pdc_r3, WORKFLOW_SENT_TO_BANK, sent_to_bank_date=t0)
	tr = _transition(pdc_r3, WORKFLOW_BOUNCED, bounced_date=t0)
	rep = _je_report(tr["je"], ctx)
	results.append({"scenario": "3_receivable_bounce", "pdc": pdc_r3.name, "transition": tr, "report": rep})
	errors.extend(
		_assert_party_policy(rep, "3_receivable_bounce", expect_both=True, expect_clear_split=False)
	)

	# 4 Receivable Clear (Registered -> Cleared direct)
	pdc_r4 = _new_receivable_pdc(ctx, _unique_cheque_no("LIVE-R-CLR"))
	_transition(pdc_r4, WORKFLOW_REGISTERED, received_date=t0)
	tr = _transition(pdc_r4, WORKFLOW_CLEARED, cleared_date=t0)
	rep = _je_report(tr["je"], ctx)
	results.append({"scenario": "4_receivable_clear", "pdc": pdc_r4.name, "transition": tr, "report": rep})
	errors.extend(_assert_party_policy(rep, "4_receivable_clear", expect_both=False, expect_clear_split=True))

	# 5 Payable Register
	pdc_p5 = _new_payable_pdc(ctx, _unique_cheque_no("LIVE-P-REG"))
	tr = _transition(pdc_p5, WORKFLOW_REGISTERED, received_date=t0)
	rep = _je_report(tr["je"], ctx)
	results.append({"scenario": "5_payable_register", "pdc": pdc_p5.name, "transition": tr, "report": rep})
	errors.extend(_assert_party_policy(rep, "5_payable_register", expect_both=True, expect_clear_split=False))

	# 6 Payable Clear
	pdc_p6 = _new_payable_pdc(ctx, _unique_cheque_no("LIVE-P-CLR"))
	_transition(pdc_p6, WORKFLOW_REGISTERED, received_date=t0)
	_transition(pdc_p6, WORKFLOW_ISSUED, handover_date=t0)
	tr = _transition(pdc_p6, WORKFLOW_CLEARED, cleared_date=t0)
	rep = _je_report(tr["je"], ctx)
	results.append({"scenario": "6_payable_clear", "pdc": pdc_p6.name, "transition": tr, "report": rep})
	errors.extend(_assert_party_policy(rep, "6_payable_clear", expect_both=False, expect_clear_split=True))

	# 8 Endorsement unchanged (holder AR debit; temporarily clear endorsement GL setting)
	holder = frappe.db.get_value(
		"Customer",
		{"disabled": 0, "name": ("!=", ctx["customer"])},
		"name",
		order_by="modified desc",
	)
	endorse_ok = True
	endorse_notes: list[str] = []
	settings_name = ctx["settings"].name
	orig_endorse_gl = ctx["settings"].default_endorsement_account
	if holder:
		try:
			if orig_endorse_gl:
				frappe.db.set_value("PDC Settings", settings_name, "default_endorsement_account", None)
			pdc_e = _new_receivable_pdc(ctx, _unique_cheque_no("LIVE-R-END"))
			_transition(pdc_e, WORKFLOW_REGISTERED, received_date=t0)
			pdc_e.holder_party_type = "Customer"
			pdc_e.holder_party = holder
			pdc_e.endorsement_settlement_account = None
			tr = _transition(pdc_e, WORKFLOW_ENDORSED, handover_date=t0)
			rep = _je_report(tr["je"], ctx)
			if rep.get("je"):
				for r in rep["accounts"]:
					if r.get("party") == ctx["customer"]:
						endorse_ok = False
						endorse_notes.append("drawer party on JE line")
					elif r.get("party") == holder:
						endorse_notes.append("holder party on line")
			else:
				endorse_ok = False
				endorse_notes.append("endorsement JE not created")
			results.append(
				{
					"scenario": "8_endorsement_unchanged",
					"pdc": pdc_e.name,
					"holder": holder,
					"drawer": ctx["customer"],
					"transition": tr,
					"report": rep,
					"endorse_ok": endorse_ok,
					"notes": endorse_notes,
				}
			)
			if not endorse_ok:
				errors.append("8_endorsement: drawer party must not appear on endorsement JE")
		finally:
			if orig_endorse_gl:
				frappe.db.set_value(
					"PDC Settings", settings_name, "default_endorsement_account", orig_endorse_gl
				)
				frappe.db.commit()
	else:
		endorse_notes.append("skipped: only one customer in site")
		results.append({"scenario": "8_endorsement_unchanged", "skipped": True, "notes": endorse_notes})

	out = {
		"site": frappe.local.site,
		"company": ctx["company"],
		"bank_gl": ctx["bank_gl"],
		"scenarios": results,
		"errors": errors,
		"passed": not errors,
	}
	print(json.dumps(out, indent=2, default=str))
	if errors:
		frappe.throw("Live orchestration E2E failed:\n" + "\n".join(errors))
	return out
