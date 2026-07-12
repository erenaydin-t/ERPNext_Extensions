"""Live E2E: Bank Dimension sourced from PDC document field only (development.localhost).

bench --site development.localhost execute erpnext_extensions.cheque_management.run_live_bank_dimension_e2e.run
"""

from __future__ import annotations

import json
from datetime import timedelta

import frappe
from frappe.utils import getdate, today

from erpnext_extensions.cheque_management.pdc_accounting_dimensions import (
	provision_post_dated_cheque_accounting_dimensions,
)
from erpnext_extensions.cheque_management.pdc_bank_dimension import (
	get_bank_accounting_dimension_fieldname,
	resolve_pdc_bank_dimension_value,
)
from erpnext_extensions.cheque_management.pdc_workflow_state_machine import (
	WORKFLOW_BOUNCED,
	WORKFLOW_CLEARED,
	WORKFLOW_REGISTERED,
	WORKFLOW_SENT_TO_BANK,
)
from erpnext_extensions.cheque_management.run_live_party_orchestration_e2e import (
	_new_receivable_pdc,
	_site_context,
	_transition,
	_unique_cheque_no,
)


def _today():
	return getdate(today())


def _je_dim_rows(je_name: str | None, dim_field: str | None) -> list[dict]:
	if not je_name or not dim_field:
		return []
	je = frappe.get_doc("Journal Entry", je_name)
	out = []
	for row in je.accounts:
		out.append(
			{
				"account": row.account,
				"party_type": row.party_type or "",
				"party": row.party or "",
				"debit": float(row.debit_in_account_currency or 0),
				"credit": float(row.credit_in_account_currency or 0),
				"dim": getattr(row, dim_field, None),
			}
		)
	return out


def _gl_dim_rows(je_name: str | None, dim_field: str | None) -> list[dict]:
	if not je_name or not dim_field:
		return []
	raw = frappe.get_all(
		"GL Entry",
		filters={"voucher_type": "Journal Entry", "voucher_no": je_name, "is_cancelled": 0},
		fields=["account", "party_type", "party", "debit", "credit", dim_field],
		order_by="idx asc",
	)
	return [{**r, "dim": r.get(dim_field)} for r in raw]


def _assert_all_dims_null(rows: list[dict], label: str, errors: list[str]) -> None:
	for r in rows:
		if r.get("dim"):
			errors.append(f"{label}: {r['account']} dim should be NULL, got {r['dim']!r}")


def _assert_dim_policy(
	rows: list[dict],
	*,
	expected: str,
	bank_gl: str | None,
	clearing_gl: str | None,
	cih_gl: str | None,
	protested_gl: str | None,
	label: str,
	errors: list[str],
) -> None:
	by_acc = {r["account"]: r for r in rows}
	for acc in {a for a in (bank_gl, clearing_gl) if a}:
		r = by_acc.get(acc)
		if not r:
			continue
		if (r.get("dim") or "") != expected:
			errors.append(f"{label}: eligible {acc} dim={r.get('dim')!r} expected {expected!r}")
	for acc in {a for a in (cih_gl, protested_gl) if a}:
		r = by_acc.get(acc)
		if r and r.get("dim"):
			errors.append(f"{label}: {acc} should have empty dim, got {r['dim']!r}")
	for acc, r in by_acc.items():
		if acc in {bank_gl, clearing_gl, cih_gl, protested_gl}:
			continue
		if r.get("dim"):
			errors.append(f"{label}: non-target {acc} should have empty dim, got {r['dim']!r}")


def _set_pdc_bank_dimension(pdc, value: str | None, dim_field: str) -> None:
	if not dim_field:
		return
	pdc.set(dim_field, value)
	pdc.flags.ignore_validate_update_after_submit = True
	pdc.save(ignore_permissions=True)
	frappe.db.commit()
	pdc.reload()


def _run_receivable_stb_bounce_clear(
	ctx: dict,
	cheque_prefix: str,
	*,
	dim_field: str,
	bank_dim_value: str | None,
	scenario_label: str,
	t0,
	errors: list[str],
) -> dict:
	clearing_gl = ctx["settings"].default_cheques_in_clearing_account
	cih_gl = ctx["settings"].default_cheques_in_hand_account
	protested_gl = ctx["settings"].default_protested_account
	bank_gl = ctx["bank_gl"]
	expected = bank_dim_value or ""

	p = _new_receivable_pdc(ctx, _unique_cheque_no(cheque_prefix))
	if bank_dim_value:
		_set_pdc_bank_dimension(p, bank_dim_value, dim_field)
	else:
		_set_pdc_bank_dimension(p, None, dim_field)
	p.reload()
	if bank_dim_value and resolve_pdc_bank_dimension_value(p) != bank_dim_value:
		errors.append(f"{scenario_label}: PDC {dim_field} not set to {bank_dim_value!r}")

	out: dict = {
		"scenario": scenario_label,
		"pdc": p.name,
		"pdc_bank_dimension": resolve_pdc_bank_dimension_value(p),
	}

	_transition(p, WORKFLOW_REGISTERED, received_date=t0)
	tr_stb = _transition(p, WORKFLOW_SENT_TO_BANK, sent_to_bank_date=t0)
	je_stb = tr_stb["je"]
	rows_stb = _je_dim_rows(je_stb, dim_field)
	gl_stb = _gl_dim_rows(je_stb, dim_field)
	if bank_dim_value:
		_assert_dim_policy(
			rows_stb,
			expected=expected,
			bank_gl=None,
			clearing_gl=clearing_gl,
			cih_gl=cih_gl,
			protested_gl=None,
			label=f"{scenario_label}_stb_je",
			errors=errors,
		)
		_assert_dim_policy(
			gl_stb,
			expected=expected,
			bank_gl=None,
			clearing_gl=clearing_gl,
			cih_gl=cih_gl,
			protested_gl=None,
			label=f"{scenario_label}_stb_gl",
			errors=errors,
		)
	else:
		_assert_all_dims_null(rows_stb, f"{scenario_label}_stb_je", errors)
		_assert_all_dims_null(gl_stb, f"{scenario_label}_stb_gl", errors)

	p.reload()
	tr_bou = _transition(p, WORKFLOW_BOUNCED, bounced_date=t0)
	je_bou = tr_bou["je"]
	rows_bou = _je_dim_rows(je_bou, dim_field)
	gl_bou = _gl_dim_rows(je_bou, dim_field)
	if bank_dim_value:
		_assert_dim_policy(
			rows_bou,
			expected=expected,
			bank_gl=None,
			clearing_gl=clearing_gl,
			cih_gl=None,
			protested_gl=protested_gl,
			label=f"{scenario_label}_bounce_je",
			errors=errors,
		)
	else:
		_assert_all_dims_null(rows_bou, f"{scenario_label}_bounce_je", errors)
		_assert_all_dims_null(gl_bou, f"{scenario_label}_bounce_gl", errors)

	p2 = _new_receivable_pdc(ctx, _unique_cheque_no(cheque_prefix + "-CLR"))
	if bank_dim_value:
		_set_pdc_bank_dimension(p2, bank_dim_value, dim_field)
	else:
		_set_pdc_bank_dimension(p2, None, dim_field)
	_transition(p2, WORKFLOW_REGISTERED, received_date=t0)
	_transition(p2, WORKFLOW_SENT_TO_BANK, sent_to_bank_date=t0)
	tr_clr = _transition(p2, WORKFLOW_CLEARED, cleared_date=t0)
	je_clr = tr_clr["je"]
	rows_clr = _je_dim_rows(je_clr, dim_field)
	gl_clr = _gl_dim_rows(je_clr, dim_field)

	bank_line = next((r for r in rows_clr if r["account"] == bank_gl), None)
	if bank_line and (bank_line.get("party_type") or bank_line.get("party")):
		errors.append(f"{scenario_label}_clear: bank line must not have party")

	if bank_dim_value:
		_assert_dim_policy(
			rows_clr,
			expected=expected,
			bank_gl=bank_gl,
			clearing_gl=clearing_gl,
			cih_gl=cih_gl,
			protested_gl=None,
			label=f"{scenario_label}_clear_je",
			errors=errors,
		)
		for r in rows_clr:
			acc = r["account"]
			if acc in {bank_gl, clearing_gl}:
				continue
			if r.get("dim"):
				errors.append(f"{scenario_label}_clear_je: {acc} unexpected dim")
		for gle in gl_clr:
			acc = gle["account"]
			dim = gle.get("dim")
			if acc in {bank_gl, clearing_gl}:
				if (dim or "") != expected:
					errors.append(f"{scenario_label}_clear_gl: {acc} dim={dim!r}")
			elif dim:
				errors.append(f"{scenario_label}_clear_gl: {acc} should be NULL")
	else:
		_assert_all_dims_null(rows_clr, f"{scenario_label}_clear_je", errors)
		_assert_all_dims_null(gl_clr, f"{scenario_label}_clear_gl", errors)

	out.update(
		{
			"send_to_bank_je": je_stb,
			"bounce_je": je_bou,
			"clear_je": je_clr,
			"send_to_bank_je_rows": rows_stb,
			"bounce_je_rows": rows_bou,
			"clear_je_rows": rows_clr,
			"clear_gl_rows": gl_clr,
		}
	)
	return out


def run():
	frappe.set_user("Administrator")
	try:
		provision_post_dated_cheque_accounting_dimensions()
		frappe.db.commit()
	except Exception:
		frappe.log_error(title="Bank Dimension E2E provision", message=frappe.get_traceback())

	ctx = _site_context()
	dim_field = get_bank_accounting_dimension_fieldname() or ""
	errors: list[str] = []
	results: list[dict] = []
	t0 = _today()

	if not dim_field:
		errors.append("No Accounting Dimension with document_type=Bank found")

	bank_for_dim = None
	if dim_field:
		bank_for_dim = frappe.db.get_value("Bank", {}, "name", order_by="modified desc")
		if not bank_for_dim:
			errors.append("No Bank master to set PDC bank_dimension in Scenario B")

	results.append(
		{
			"provisioning": {
				"bank_dimension_field": dim_field,
				"note": "JE/GL bank dimension copied only from PDC document field; bank_account ignored.",
			}
		}
	)

	# Scenario A — empty bank_dimension, bank_account still set via _new_receivable_pdc
	results.append(
		_run_receivable_stb_bounce_clear(
			ctx,
			"BD-A",
			dim_field=dim_field,
			bank_dim_value=None,
			scenario_label="scenario_a_empty",
			t0=t0,
			errors=errors,
		)
	)

	# Scenario B — explicit PDC bank_dimension
	if bank_for_dim:
		results.append(
			_run_receivable_stb_bounce_clear(
				ctx,
				"BD-B",
				dim_field=dim_field,
				bank_dim_value=bank_for_dim,
				scenario_label="scenario_b_populated",
				t0=t0,
				errors=errors,
			)
		)

	out = {
		"passed": not errors,
		"errors": errors,
		"dim_field": dim_field,
		"scenario_b_bank": bank_for_dim,
		"results": results,
	}
	print(json.dumps(out, indent=2, default=str))
	if errors:
		frappe.throw("Bank Dimension E2E failed:\n" + "\n".join(errors))
	return out
