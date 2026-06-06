"""Live E2E: Bank Dimension + Bank Account Dimension on PDC JEs (development.localhost).

bench --site development.localhost execute \\
  erpnext_extensions.cheque_management.run_live_pdc_bank_related_dimensions_e2e.run
"""

from __future__ import annotations

import json

import frappe
from frappe.utils import cint, getdate, today

from erpnext_extensions.cheque_management.pdc_accounting_dimensions import (
	provision_post_dated_cheque_accounting_dimensions,
	sync_pdc_accounting_dimension_fields_allow_on_submit,
)
from erpnext_extensions.cheque_management.pdc_bank_dimension import (
	get_bank_account_dimension_fieldname,
	get_bank_accounting_dimension_fieldname,
	get_pdc_bank_related_accounting_dimensions,
	resolve_pdc_accounting_dimension_value,
)
from erpnext_extensions.cheque_management.pdc_workflow_state_machine import (
	WORKFLOW_BOUNCED,
	WORKFLOW_CLEARED,
	WORKFLOW_ISSUED,
	WORKFLOW_REGISTERED,
	WORKFLOW_SENT_TO_BANK,
)
from erpnext_extensions.cheque_management.run_live_party_orchestration_e2e import (
	_new_payable_pdc,
	_new_receivable_pdc,
	_site_context,
	_transition,
	_unique_cheque_no,
)


def _today():
	return getdate(today())


def _set_pdc_dims(pdc, *, bank_fn: str | None, bank_val: str | None, ba_fn: str | None, ba_val: str | None) -> None:
	if bank_fn:
		pdc.set(bank_fn, bank_val)
	if ba_fn:
		pdc.set(ba_fn, ba_val)
	pdc.flags.ignore_validate_update_after_submit = True
	pdc.save(ignore_permissions=True)
	frappe.db.commit()
	pdc.reload()


def _je_rows(je_name: str | None, dim_fields: list[str]) -> list[dict]:
	if not je_name:
		return []
	je = frappe.get_doc("Journal Entry", je_name)
	out = []
	for row in je.accounts:
		item = {
			"account": row.account,
			"debit": float(row.debit_in_account_currency or 0),
			"credit": float(row.credit_in_account_currency or 0),
		}
		for fn in dim_fields:
			item[fn] = getattr(row, fn, None) if fn else None
		out.append(item)
	return out


def _gl_rows(je_name: str | None, dim_fields: list[str]) -> list[dict]:
	if not je_name or not dim_fields:
		return []
	fields = ["account", "debit", "credit", *dim_fields]
	raw = frappe.get_all(
		"GL Entry",
		filters={"voucher_type": "Journal Entry", "voucher_no": je_name, "is_cancelled": 0},
		fields=fields,
		order_by="idx asc",
	)
	return raw


def _assert_all_dims_empty(rows: list[dict], dim_fields: list[str], label: str, errors: list[str]) -> None:
	for r in rows:
		for fn in dim_fields:
			if r.get(fn):
				errors.append(f"{label}: {r['account']} {fn} should be empty, got {r[fn]!r}")


def _assert_dim_expectations(
	rows: list[dict],
	*,
	dim_fields: list[str],
	expected: dict[str, str | None],
	eligible_accounts: set[str],
	ineligible_accounts: set[str],
	label: str,
	errors: list[str],
) -> None:
	by_acc = {r["account"]: r for r in rows}
	for acc in eligible_accounts:
		if acc not in by_acc:
			continue
		r = by_acc[acc]
		for fn in dim_fields:
			exp = expected.get(fn)
			got = r.get(fn)
			if exp:
				if (got or "") != exp:
					errors.append(f"{label}: {acc} {fn}={got!r} expected {exp!r}")
			elif got:
				errors.append(f"{label}: {acc} {fn} should be empty, got {got!r}")
	for acc in ineligible_accounts:
		r = by_acc.get(acc)
		if not r:
			continue
		for fn in dim_fields:
			if r.get(fn):
				errors.append(f"{label}: ineligible {acc} {fn}={r[fn]!r}")


def _run_receivable_flow(
	ctx: dict,
	prefix: str,
	*,
	bank_fn: str | None,
	bank_val: str | None,
	ba_fn: str | None,
	ba_val: str | None,
	dim_fields: list[str],
	test_id: str,
	t0,
	errors: list[str],
	include_bounce: bool = True,
) -> dict:
	clearing_gl = ctx["settings"].default_cheques_in_clearing_account
	cih_gl = ctx["settings"].default_cheques_in_hand_account
	protested_gl = ctx["settings"].default_protested_account
	bank_gl = ctx["bank_gl"]
	expected = {}
	if bank_fn:
		expected[bank_fn] = bank_val
	if ba_fn:
		expected[ba_fn] = ba_val

	p = _new_receivable_pdc(ctx, _unique_cheque_no(prefix))
	assert p.bank_account, f"{test_id}: PDC bank_account must be set (no dim derivation test)"
	_set_pdc_dims(p, bank_fn=bank_fn, bank_val=bank_val, ba_fn=ba_fn, ba_val=ba_val)
	if bank_fn and bank_val and resolve_pdc_accounting_dimension_value(p, bank_fn) != bank_val:
		errors.append(f"{test_id}: PDC {bank_fn} not set")
	if ba_fn and ba_val and resolve_pdc_accounting_dimension_value(p, ba_fn) != ba_val:
		errors.append(f"{test_id}: PDC {ba_fn} not set")

	out: dict = {
		"test_id": test_id,
		"pdc": p.name,
		"pdc_bank_account": p.bank_account,
		"expected_dims": expected,
		"passed": True,
	}

	_transition(p, WORKFLOW_REGISTERED, received_date=t0)
	tr_stb = _transition(p, WORKFLOW_SENT_TO_BANK, sent_to_bank_date=t0)
	je_stb = tr_stb["je"]
	rows_stb = _je_rows(je_stb, dim_fields)
	gl_stb = _gl_rows(je_stb, dim_fields)
	out["send_to_bank_je"] = je_stb
	out["send_to_bank_je_rows"] = rows_stb
	out["send_to_bank_gl_rows"] = gl_stb

	if not bank_val and not ba_val:
		_assert_all_dims_empty(rows_stb, dim_fields, f"{test_id}_stb_je", errors)
		_assert_all_dims_empty(gl_stb, dim_fields, f"{test_id}_stb_gl", errors)
	else:
		_assert_dim_expectations(
			rows_stb,
			dim_fields=dim_fields,
			expected=expected,
			eligible_accounts={clearing_gl} if clearing_gl else set(),
			ineligible_accounts={cih_gl} if cih_gl else set(),
			label=f"{test_id}_stb_je",
			errors=errors,
		)

	if include_bounce:
		p.reload()
		tr_bou = _transition(p, WORKFLOW_BOUNCED, bounced_date=t0)
		je_bou = tr_bou["je"]
		rows_bou = _je_rows(je_bou, dim_fields)
		gl_bou = _gl_rows(je_bou, dim_fields)
		out["bounce_je"] = je_bou
		out["bounce_je_rows"] = rows_bou
		out["bounce_gl_rows"] = gl_bou
		if not bank_val and not ba_val:
			_assert_all_dims_empty(rows_bou, dim_fields, f"{test_id}_bounce_je", errors)
		else:
			_assert_dim_expectations(
				rows_bou,
				dim_fields=dim_fields,
				expected=expected,
				eligible_accounts={clearing_gl} if clearing_gl else set(),
				ineligible_accounts={protested_gl} if protested_gl else set(),
				label=f"{test_id}_bounce_je",
				errors=errors,
			)

	p2 = _new_receivable_pdc(ctx, _unique_cheque_no(prefix + "-CLR"))
	_set_pdc_dims(p2, bank_fn=bank_fn, bank_val=bank_val, ba_fn=ba_fn, ba_val=ba_val)
	_transition(p2, WORKFLOW_REGISTERED, received_date=t0)
	_transition(p2, WORKFLOW_SENT_TO_BANK, sent_to_bank_date=t0)
	tr_clr = _transition(p2, WORKFLOW_CLEARED, cleared_date=t0)
	je_clr = tr_clr["je"]
	rows_clr = _je_rows(je_clr, dim_fields)
	gl_clr = _gl_rows(je_clr, dim_fields)
	out["clear_je"] = je_clr
	out["clear_je_rows"] = rows_clr
	out["clear_gl_rows"] = gl_clr

	eligible_clr = {a for a in (bank_gl, clearing_gl) if a}
	ineligible_clr = {cih_gl} if cih_gl else set()
	if not bank_val and not ba_val:
		_assert_all_dims_empty(rows_clr, dim_fields, f"{test_id}_clear_je", errors)
		_assert_all_dims_empty(gl_clr, dim_fields, f"{test_id}_clear_gl", errors)
	else:
		_assert_dim_expectations(
			rows_clr,
			dim_fields=dim_fields,
			expected=expected,
			eligible_accounts=eligible_clr,
			ineligible_accounts=ineligible_clr,
			label=f"{test_id}_clear_je",
			errors=errors,
		)

	out["passed"] = not any(e.startswith(test_id) for e in errors)
	return out


def _run_payable_clear(
	ctx: dict,
	*,
	bank_fn: str | None,
	bank_val: str | None,
	ba_fn: str | None,
	ba_val: str | None,
	dim_fields: list[str],
	test_id: str,
	t0,
	errors: list[str],
) -> dict:
	bank_gl = ctx["bank_gl"]
	pool_gl = ctx["settings"].default_payable_cheque_account
	expected = {}
	if bank_fn:
		expected[bank_fn] = bank_val
	if ba_fn:
		expected[ba_fn] = ba_val

	p = _new_payable_pdc(ctx, _unique_cheque_no("PAY-CLR"))
	_set_pdc_dims(p, bank_fn=bank_fn, bank_val=bank_val, ba_fn=ba_fn, ba_val=ba_val)
	_transition(p, WORKFLOW_REGISTERED, received_date=t0)
	_transition(p, WORKFLOW_ISSUED, handover_date=t0)
	tr = _transition(p, WORKFLOW_CLEARED, cleared_date=t0)
	je = tr["je"]
	rows = _je_rows(je, dim_fields)
	gl = _gl_rows(je, dim_fields)

	credit_bank = [r for r in rows if r["account"] == bank_gl and r["credit"] > 0]
	debit_pool = [r for r in rows if r["account"] == pool_gl and r["debit"] > 0]

	if bank_val or ba_val:
		_assert_dim_expectations(
			rows,
			dim_fields=dim_fields,
			expected=expected,
			eligible_accounts={bank_gl} if bank_gl else set(),
			ineligible_accounts={pool_gl} if pool_gl else set(),
			label=f"{test_id}_payable_clear_je",
			errors=errors,
		)
	else:
		_assert_all_dims_empty(rows, dim_fields, f"{test_id}_payable_clear_je", errors)

	return {
		"test_id": test_id,
		"pdc": p.name,
		"clear_je": je,
		"je_rows": rows,
		"gl_rows": gl,
		"credit_bank_lines": credit_bank,
		"debit_pool_lines": debit_pool,
		"passed": not any(e.startswith(test_id) for e in errors),
	}


def run():
	frappe.set_user("Administrator")
	provision_post_dated_cheque_accounting_dimensions()
	sync_pdc_accounting_dimension_fields_allow_on_submit()
	frappe.db.commit()

	ctx = _site_context()
	bank_fn = get_bank_accounting_dimension_fieldname()
	ba_fn = get_bank_account_dimension_fieldname()
	dim_fields = [fn for fn in (bank_fn, ba_fn) if fn]
	errors: list[str] = []
	cases: list[dict] = []
	t0 = _today()

	bank_master = frappe.db.get_value("Bank", {}, "name", order_by="modified desc")
	ba_master = frappe.db.get_value(
		"Bank Account", {"company": ctx["company"], "disabled": 0}, "name", order_by="modified desc"
	)
	if not bank_fn:
		errors.append("setup: Bank Dimension field missing")
	if not ba_fn:
		errors.append("setup: Bank Account Dimension field missing")

	cases.append(
		_run_receivable_flow(
			ctx,
			"BRD-A",
			bank_fn=bank_fn,
			bank_val=None,
			ba_fn=ba_fn,
			ba_val=None,
			dim_fields=dim_fields,
			test_id="A",
			t0=t0,
			errors=errors,
		)
	)

	if bank_master:
		cases.append(
			_run_receivable_flow(
				ctx,
				"BRD-B",
				bank_fn=bank_fn,
				bank_val=bank_master,
				ba_fn=ba_fn,
				ba_val=None,
				dim_fields=dim_fields,
				test_id="B",
				t0=t0,
				errors=errors,
			)
		)

	if ba_master:
		cases.append(
			_run_receivable_flow(
				ctx,
				"BRD-C",
				bank_fn=bank_fn,
				bank_val=None,
				ba_fn=ba_fn,
				ba_val=ba_master,
				dim_fields=dim_fields,
				test_id="C",
				t0=t0,
				errors=errors,
			)
		)

	if bank_master and ba_master:
		cases.append(
			_run_receivable_flow(
				ctx,
				"BRD-D",
				bank_fn=bank_fn,
				bank_val=bank_master,
				ba_fn=ba_fn,
				ba_val=ba_master,
				dim_fields=dim_fields,
				test_id="D",
				t0=t0,
				errors=errors,
			)
		)

	# E covered in A-D bounce legs; explicit label
	bounce_case = next((c for c in cases if c.get("test_id") == "D"), cases[-1] if cases else {})
	cases.append(
		{
			"test_id": "E",
			"note": "Bounce credit clearing / debit protested — see test D bounce_je_rows",
			"bounce_je": bounce_case.get("bounce_je"),
			"bounce_je_rows": bounce_case.get("bounce_je_rows"),
			"passed": bool(bounce_case.get("bounce_je")),
		}
	)

	if bank_master and ba_master:
		cases.append(
			_run_payable_clear(
				ctx,
				bank_fn=bank_fn,
				bank_val=bank_master,
				ba_fn=ba_fn,
				ba_val=ba_master,
				dim_fields=dim_fields,
				test_id="F",
				t0=t0,
				errors=errors,
			)
		)

	meta = frappe.get_meta("Post Dated Cheque", cached=False)
	ba_df = meta.get_field(ba_fn) if ba_fn else None
	cf_allow = None
	if ba_fn:
		cf_allow = frappe.db.get_value("Custom Field", {"dt": "Post Dated Cheque", "fieldname": ba_fn}, "allow_on_submit")
	g_ok = bool(ba_fn and frappe.db.exists("Custom Field", {"dt": "Post Dated Cheque", "fieldname": ba_fn}))
	allow_ok = cint(cf_allow or (ba_df.allow_on_submit if ba_df else 0)) == 1
	cases.append(
		{
			"test_id": "G",
			"bank_account_dimension_field": ba_fn,
			"custom_field_exists": g_ok,
			"allow_on_submit": cint(cf_allow or (ba_df.allow_on_submit if ba_df else 0)),
			"related_dimensions": get_pdc_bank_related_accounting_dimensions(),
			"passed": g_ok and allow_ok,
		}
	)
	if not allow_ok:
		errors.append("G: bank_account_dimension allow_on_submit != 1")

	out = {
		"passed": not errors,
		"errors": errors,
		"site": frappe.local.site,
		"dim_fields": dim_fields,
		"no_derivation_note": "Values set only on PDC dimension fields; bank_account on PDC is unrelated.",
		"cases": cases,
	}
	print(json.dumps(out, indent=2, default=str))
	if errors:
		raise frappe.ValidationError("Bank-related dimensions E2E failed:\n" + "\n".join(errors))
	return out
