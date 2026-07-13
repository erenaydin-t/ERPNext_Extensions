"""Live E2E: Receivable/Payable intermediary accounts on clear (development.localhost).

bench --site development.localhost execute erpnext_extensions.cheque_management.run_live_clear_intermediary_policy_e2e.run
"""

from __future__ import annotations

import json
import time
from datetime import timedelta

import frappe
from frappe.utils import getdate, today

from erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque import (
	_pdc_validate_clearing_bank_ledger_account,
)
from erpnext_extensions.cheque_management.pdc_workflow_state_machine import (
	WORKFLOW_BOUNCED,
	WORKFLOW_CLEARED,
	WORKFLOW_DRAFT,
	WORKFLOW_ENDORSED,
	WORKFLOW_ISSUED,
	WORKFLOW_REGISTERED,
	WORKFLOW_SENT_TO_BANK,
	WORKFLOW_UNDER_LEGAL_ACTION,
)
from erpnext_extensions.cheque_management.run_live_party_orchestration_e2e import (
	_assert_party_policy,
	_je_report,
	_new_payable_pdc,
	_new_receivable_pdc,
	_site_context,
	_transition,
	_unique_cheque_no,
)


def _today():
	return getdate(today())


def _account_type(acc: str | None) -> str | None:
	if not acc or not frappe.db.exists("Account", acc):
		return None
	return frappe.db.get_value("Account", acc, "account_type")


def run():
	frappe.set_user("Administrator")
	ctx = _site_context()
	settings = ctx["settings"]
	errors: list[str] = []
	results: list[dict] = []
	t0 = _today()

	clearing_acc = settings.default_cheques_in_clearing_account
	protested_acc = settings.default_protested_account
	pool_acc = settings.default_payable_cheque_account

	results.append(
		{
			"coa_snapshot": {
				"clearing": clearing_acc,
				"clearing_account_type": _account_type(clearing_acc),
				"protested": protested_acc,
				"protested_account_type": _account_type(protested_acc),
				"payable_pool": pool_acc,
				"payable_pool_account_type": _account_type(pool_acc),
				"bank_gl": ctx["bank_gl"],
				"bank_gl_account_type": _account_type(ctx["bank_gl"]),
			}
		}
	)

	# Test A — Receivable Clear after Sent to Bank (clearing account may be Receivable)
	pdc_a = _new_receivable_pdc(ctx, _unique_cheque_no("CLR-A"))
	_transition(pdc_a, WORKFLOW_REGISTERED, received_date=t0)
	_transition(pdc_a, WORKFLOW_SENT_TO_BANK, sent_to_bank_date=t0)
	tr = _transition(pdc_a, WORKFLOW_CLEARED, cleared_date=t0)
	rep = _je_report(tr["je"], ctx)
	results.append(
		{"test": "A_receivable_clear_after_sent_to_bank", "pdc": pdc_a.name, "transition": tr, "report": rep}
	)
	errors.extend(_assert_party_policy(rep, "A", expect_both=False, expect_clear_split=True))
	if clearing_acc:
		cr = [r for r in rep["accounts"] if r.get("credit")][0]
		if cr.get("account") != clearing_acc:
			errors.append(f"A: expected credit on {clearing_acc}, got {cr.get('account')}")

	# Test B — Under Legal Action → Cleared (protested / clearing)
	if protested_acc and _account_type(protested_acc) in ("Receivable", "Payable", None, ""):
		pdc_b = _new_receivable_pdc(ctx, _unique_cheque_no("CLR-B"))
		_transition(pdc_b, WORKFLOW_REGISTERED, received_date=t0)
		_transition(pdc_b, WORKFLOW_SENT_TO_BANK, sent_to_bank_date=t0)
		_transition(pdc_b, WORKFLOW_BOUNCED, bounced_date=t0)
		_transition(pdc_b, WORKFLOW_UNDER_LEGAL_ACTION)
		tr = _transition(pdc_b, WORKFLOW_CLEARED, cleared_date=t0)
		rep = _je_report(tr["je"], ctx)
		results.append(
			{"test": "B_clear_from_under_legal_action", "pdc": pdc_b.name, "transition": tr, "report": rep}
		)
		errors.extend(_assert_party_policy(rep, "B", expect_both=False, expect_clear_split=True))
	else:
		results.append(
			{"test": "B_clear_from_under_legal_action", "skipped": True, "reason": "no protested account"}
		)

	# Test C — Payable Clear (pool may be Payable type)
	pdc_c = _new_payable_pdc(ctx, _unique_cheque_no("CLR-C"))
	_transition(pdc_c, WORKFLOW_REGISTERED, received_date=t0)
	_transition(pdc_c, WORKFLOW_ISSUED, handover_date=t0)
	tr = _transition(pdc_c, WORKFLOW_CLEARED, cleared_date=t0)
	rep = _je_report(tr["je"], ctx)
	results.append({"test": "C_payable_clear", "pdc": pdc_c.name, "transition": tr, "report": rep})
	errors.extend(_assert_party_policy(rep, "C", expect_both=False, expect_clear_split=True))

	# Test D — Bank safety: Receivable-typed GL must be rejected
	ar_gl = frappe.db.get_value(
		"Account",
		{"company": ctx["company"], "account_type": "Receivable", "is_group": 0},
		"name",
	)
	if ar_gl:
		doc_stub = frappe._dict(company=ctx["company"], bank_account=ctx["bank_account"])
		try:
			_pdc_validate_clearing_bank_ledger_account(doc_stub, ar_gl)
			errors.append("D: expected bank validation to reject Receivable GL")
		except frappe.ValidationError as e:
			results.append(
				{"test": "D_bank_rejects_receivable_gl", "gl": ar_gl, "ok": True, "message": str(e)}
			)
	else:
		results.append({"test": "D_bank_rejects_receivable_gl", "skipped": True})

	# Test E — Send To Bank regression
	pdc_e = _new_receivable_pdc(ctx, _unique_cheque_no("CLR-E-STB"))
	_transition(pdc_e, WORKFLOW_REGISTERED, received_date=t0)
	tr = _transition(pdc_e, WORKFLOW_SENT_TO_BANK, sent_to_bank_date=t0)
	rep = _je_report(tr["je"], ctx)
	results.append({"test": "E_send_to_bank", "transition": tr, "report": rep})
	errors.extend(_assert_party_policy(rep, "E", expect_both=True, expect_clear_split=False))

	# Test F — Bounce regression
	pdc_f = _new_receivable_pdc(ctx, _unique_cheque_no("CLR-F-BOU"))
	_transition(pdc_f, WORKFLOW_REGISTERED, received_date=t0)
	_transition(pdc_f, WORKFLOW_SENT_TO_BANK, sent_to_bank_date=t0)
	tr = _transition(pdc_f, WORKFLOW_BOUNCED, bounced_date=t0)
	rep = _je_report(tr["je"], ctx)
	results.append({"test": "F_bounce", "transition": tr, "report": rep})
	errors.extend(_assert_party_policy(rep, "F", expect_both=True, expect_clear_split=False))

	# Test G — Endorsement unchanged (smoke)
	holder = frappe.db.get_value(
		"Customer",
		{"disabled": 0, "name": ("!=", ctx["customer"])},
		"name",
	)
	if holder:
		settings_name = settings.name
		orig = settings.default_endorsement_account
		try:
			if orig:
				frappe.db.set_value("PDC Settings", settings_name, "default_endorsement_account", None)
			pdc_g = _new_receivable_pdc(ctx, _unique_cheque_no("CLR-G-END"))
			_transition(pdc_g, WORKFLOW_REGISTERED, received_date=t0)
			pdc_g.holder_party_type = "Customer"
			pdc_g.holder_party = holder
			tr = _transition(pdc_g, WORKFLOW_ENDORSED, handover_date=t0)
			rep = _je_report(tr["je"], ctx)
			for r in rep.get("accounts") or []:
				if r.get("party") == ctx["customer"]:
					errors.append("G: drawer on endorsement JE")
			results.append({"test": "G_endorsement", "transition": tr, "report": rep})
		finally:
			if orig:
				frappe.db.set_value("PDC Settings", settings_name, "default_endorsement_account", orig)
				frappe.db.commit()

	out = {"passed": not errors, "errors": errors, "results": results, "company": ctx["company"]}
	print(json.dumps(out, indent=2, default=str))
	if errors:
		frappe.throw("Clear intermediary policy E2E failed:\n" + "\n".join(errors))
	return out
