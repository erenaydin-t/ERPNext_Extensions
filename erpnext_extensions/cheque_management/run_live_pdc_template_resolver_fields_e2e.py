"""Live E2E: PDC account/dimension fields as templates for future JEs (development.localhost).

bench --site development.localhost execute \\
  erpnext_extensions.cheque_management.run_live_pdc_template_resolver_fields_e2e.run
"""

from __future__ import annotations

import json
import time
from datetime import timedelta

import frappe
from frappe.utils import cint, getdate, today

from erpnext_extensions.cheque_management.doctype.cheque_opening_import.cheque_opening_import import (
	TEMPLATE_HEADERS,
)
from erpnext_extensions.cheque_management.pdc_accounting_dimensions import (
	provision_post_dated_cheque_accounting_dimensions,
	sync_pdc_accounting_dimension_fields_allow_on_submit,
)
from erpnext_extensions.cheque_management.pdc_bank_dimension import (
	get_bank_accounting_dimension_fieldname,
	resolve_pdc_bank_dimension_value,
)
from erpnext_extensions.cheque_management.pdc_workflow_state_machine import (
	WORKFLOW_CLEARED,
	WORKFLOW_REGISTERED,
	WORKFLOW_SENT_TO_BANK,
)
from erpnext_extensions.cheque_management.run_live_party_orchestration_e2e import (
	_je_for_transition,
	_new_receivable_pdc,
	_site_context,
	_transition,
	_unique_cheque_no,
)


def _today():
	return getdate(today())


def _je_ref_count(pdc_name: str) -> int:
	return frappe.db.count(
		"PDC Journal Reference",
		{"parent": pdc_name, "parenttype": "Post Dated Cheque"},
	)


def _alt_gl_account(company: str, reference: str | None, *also_exclude: str) -> str | None:
	ex = {reference, *also_exclude}
	ex = {e for e in ex if e}
	if not reference:
		return None
	ref = frappe.db.get_value("Account", reference, ["account_type", "root_type"], as_dict=True)
	if not ref:
		return None
	candidates = frappe.get_all(
		"Account",
		filters={
			"company": company,
			"is_group": 0,
			"disabled": 0,
			"account_type": ref.account_type,
			"root_type": ref.root_type,
			"name": ["not in", list(ex)],
		},
		pluck="name",
		order_by="modified desc",
		limit=5,
	)
	return candidates[0] if candidates else None


def _save_pdc_template_fields(pdc, **fields) -> None:
	for k, v in fields.items():
		pdc.set(k, v)
	pdc.flags.ignore_validate_update_after_submit = True
	pdc.save(ignore_permissions=True)
	frappe.db.commit()
	pdc.reload()


def _je_accounts_snapshot(je_name: str) -> list[dict]:
	if not je_name:
		return []
	je = frappe.get_doc("Journal Entry", je_name)
	return [
		{
			"account": row.account,
			"debit": float(row.debit_in_account_currency or 0),
			"credit": float(row.credit_in_account_currency or 0),
		}
		for row in je.accounts
	]


def _je_row_dim(je_name: str, dim_field: str) -> list[dict]:
	if not je_name or not dim_field:
		return []
	je = frappe.get_doc("Journal Entry", je_name)
	return [
		{"account": row.account, "dim": getattr(row, dim_field, None)}
		for row in je.accounts
	]


def _ensure_site_pdc_settings(company: str) -> None:
	from erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque import (
		_get_pdc_settings_for_company,
	)

	if _get_pdc_settings_for_company(company):
		return
	orphan = frappe.db.get_value(
		"PDC Settings",
		{"default_cheques_in_hand_account": ("is", "set")},
		"name",
		order_by="modified desc",
	)
	if orphan and frappe.db.exists("Company", company):
		frappe.db.set_value("PDC Settings", orphan, "company", company)
		frappe.db.commit()


def _test4_dimension_allow_on_submit() -> dict:
	provision_post_dated_cheque_accounting_dimensions()
	sync_pdc_accounting_dimension_fields_allow_on_submit()
	try:
		from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import (
			get_accounting_dimensions,
		)
	except Exception:

		def get_accounting_dimensions():
			return []

	fieldnames = set(get_accounting_dimensions() or [])
	fieldnames.update({"project", "cost_center"})
	meta = frappe.get_meta("Post Dated Cheque", cached=False)
	missing_allow = []
	for fn in sorted(fieldnames):
		if not fn or not meta.get_field(fn):
			continue
		df = meta.get_field(fn)
		if not cint(df.allow_on_submit):
			missing_allow.append(fn)
	return {
		"test_id": 4,
		"dimension_fields_checked": sorted(fieldnames),
		"missing_allow_on_submit": missing_allow,
		"passed": not missing_allow,
	}


def _import_registered_pdc_via_coi(ctx: dict, cheque_no: str) -> tuple[str, str]:
	import openpyxl

	suffix = str(int(time.time()))
	fname = f"pdc_template_e2e_coi_{suffix}.xlsx"
	site_path = frappe.get_site_path("private", "files", fname)
	t0 = _today()
	wb = openpyxl.Workbook()
	ws = wb.active
	ws.title = "Data"
	ws.append(TEMPLATE_HEADERS)
	ws.append(
		[
			"Receivable",
			ctx["company"],
			ctx["bank_account"],
			"",
			cheque_no,
			t0 + timedelta(days=30),
			"100",
			"Customer",
			ctx["customer"],
			"Registered",
			ctx.get("drawer_bank") or frappe.db.get_value("Bank", {}, "name"),
			t0,
			None,
			None,
			None,
			None,
			None,
			f"SAYAD-{suffix}"[:32],
			1,
		]
	)
	wb.save(site_path)
	file_url = f"/private/files/{fname}"
	frappe.get_doc(
		{"doctype": "File", "file_name": fname, "file_url": file_url, "is_private": 1, "folder": "Home"}
	).insert(ignore_permissions=True)
	frappe.db.commit()
	coi = frappe.get_doc({"doctype": "Cheque Opening Import", "import_file": file_url})
	coi.insert(ignore_permissions=True)
	frappe.db.commit()
	coi.preview_file()
	frappe.db.commit()
	coi.reload()
	coi.execute_import()
	frappe.db.commit()
	coi.reload()
	pdc_name = None
	for row in coi.items or []:
		if row.row_status == "Imported":
			pdc_name = row.imported_pdc
			break
	if not pdc_name:
		frappe.throw(f"COI import failed: {coi.name} status={coi.import_status}")
	return coi.name, pdc_name


def run():
	frappe.set_user("Administrator")
	errors: list[str] = []
	results: dict = {"tests": []}

	ctx = _site_context()
	_ensure_site_pdc_settings(ctx["company"])
	ctx = _site_context()
	provision_post_dated_cheque_accounting_dimensions()
	sync_pdc_accounting_dimension_fields_allow_on_submit()

	dim_field = get_bank_accounting_dimension_fieldname()
	default_clearing = ctx["settings"].default_cheques_in_clearing_account
	alt_clearing = _alt_gl_account(ctx["company"], default_clearing)
	if not alt_clearing:
		alt_clearing = default_clearing
		errors.append("Setup: no alternate clearing account; using default for Test 1")

	t0 = _today()

	# Test 1 — account future effect
	p1 = _new_receivable_pdc(ctx, _unique_cheque_no("TPL-ACC"))
	_transition(p1, WORKFLOW_REGISTERED, received_date=t0)
	p1.reload()
	refs_after_reg = _je_ref_count(p1.name)
	_save_pdc_template_fields(p1, cheques_in_clearing_account=alt_clearing)
	refs_after_save = _je_ref_count(p1.name)
	if refs_after_save != refs_after_reg:
		errors.append(f"Test1: JE ref count changed on save-only ({refs_after_reg} -> {refs_after_save})")
	tr_stb = _transition(p1, WORKFLOW_SENT_TO_BANK, sent_to_bank_date=t0)
	je_stb = tr_stb.get("je")
	stb_debits = [a for a in _je_accounts_snapshot(je_stb) if a["debit"] > 0]
	uses_alt = any(a["account"] == alt_clearing for a in stb_debits)
	if not uses_alt:
		errors.append(f"Test1: STB JE debit accounts {stb_debits} expected clearing {alt_clearing!r}")
	results["tests"].append(
		{
			"test_id": 1,
			"pdc": p1.name,
			"alt_clearing": alt_clearing,
			"je_refs_after_register": refs_after_reg,
			"je_refs_after_save_only": refs_after_save,
			"stb_je": je_stb,
			"stb_debit_accounts": [a["account"] for a in stb_debits],
			"passed": refs_after_save == refs_after_reg and uses_alt,
		}
	)

	# Test 2 — dimension future effect
	bank_row = frappe.db.get_value("Bank", {}, "name", order_by="modified desc")
	bank_row2 = frappe.db.sql(
		"SELECT name FROM tabBank WHERE name != %s ORDER BY modified DESC LIMIT 1",
		(bank_row,),
	)
	bank_alt = bank_row2[0][0] if bank_row2 else bank_row

	p2 = _new_receivable_pdc(ctx, _unique_cheque_no("TPL-DIM"))
	if dim_field:
		_save_pdc_template_fields(p2, **{dim_field: bank_row})
	_transition(p2, WORKFLOW_REGISTERED, received_date=t0)
	_transition(p2, WORKFLOW_SENT_TO_BANK, sent_to_bank_date=t0)
	p2.reload()
	refs_before = _je_ref_count(p2.name)
	if dim_field:
		_save_pdc_template_fields(p2, **{dim_field: bank_alt})
	refs_after = _je_ref_count(p2.name)
	if refs_after != refs_before:
		errors.append(f"Test2: JE ref count changed on dimension save ({refs_before} -> {refs_after})")
	tr_clr = _transition(p2, WORKFLOW_CLEARED, cleared_date=t0)
	je_clr = tr_clr.get("je")
	dim_rows = _je_row_dim(je_clr, dim_field) if dim_field else []
	bank_gl = ctx["bank_gl"]
	bank_line_dims = [r["dim"] for r in dim_rows if r["account"] == bank_gl and r.get("dim")]
	dim_ok = (not dim_field) or (bank_alt in bank_line_dims)
	if dim_field and not dim_ok:
		errors.append(f"Test2: Clear JE bank line dims {dim_rows} expected {bank_alt!r}")
	results["tests"].append(
		{
			"test_id": 2,
			"pdc": p2.name,
			"dim_field": dim_field,
			"bank_dim_after_edit": resolve_pdc_bank_dimension_value(p2) if dim_field else None,
			"je_refs_before_dim_save": refs_before,
			"je_refs_after_dim_save": refs_after,
			"clear_je": je_clr,
			"clear_je_dim_rows": dim_rows,
			"passed": refs_after == refs_before and dim_ok,
		}
	)

	# Test 3 — existing JE unchanged
	p3 = _new_receivable_pdc(ctx, _unique_cheque_no("TPL-OLDJE"))
	_transition(p3, WORKFLOW_REGISTERED, received_date=t0)
	p3.reload()
	reg_key = None
	for ref in p3.journal_references or []:
		if (ref.purpose or "") == "Receive" and ref.journal_entry:
			reg_key = ref.journal_entry
			break
	snap_before = _je_accounts_snapshot(reg_key)
	cc = frappe.db.get_value(
		"Cost Center", {"company": ctx["company"], "is_group": 0}, "name", order_by="modified desc"
	)
	_save_pdc_template_fields(
		p3,
		cheques_in_clearing_account=alt_clearing,
		cost_center=cc,
		**( {dim_field: bank_alt} if dim_field else {} ),
	)
	snap_after = _je_accounts_snapshot(reg_key)
	if snap_before != snap_after:
		errors.append("Test3: Register JE rows changed after template field edit")
	results["tests"].append(
		{
			"test_id": 3,
			"pdc": p3.name,
			"register_je": reg_key,
			"je_snapshot_unchanged": snap_before == snap_after,
			"passed": snap_before == snap_after,
		}
	)

	t4 = _test4_dimension_allow_on_submit()
	results["tests"].append(t4)
	if not t4.get("passed"):
		errors.append(f"Test4: missing allow_on_submit on {t4.get('missing_allow_on_submit')}")

	# Test 5 — opening import
	drawer = frappe.db.get_value("Bank", {}, "name", order_by="modified desc")
	ctx5 = {**ctx, "drawer_bank": drawer}
	coi_name, p5_name = _import_registered_pdc_via_coi(ctx5, _unique_cheque_no("TPL-COI"))
	p5 = frappe.get_doc("Post Dated Cheque", p5_name)
	refs_open = _je_ref_count(p5_name)
	if refs_open != 0:
		errors.append(f"Test5: opening import should have 0 JE refs, got {refs_open}")
	alt2 = _alt_gl_account(ctx["company"], default_clearing, alt_clearing)
	_save_pdc_template_fields(p5, cheques_in_clearing_account=alt2 or alt_clearing)
	refs_mid = _je_ref_count(p5_name)
	tr5 = _transition(p5, WORKFLOW_SENT_TO_BANK, sent_to_bank_date=t0)
	je5 = tr5.get("je")
	stb5 = [a for a in _je_accounts_snapshot(je5) if a["debit"] > 0]
	exp_clear = alt2 or alt_clearing
	ok5 = any(a["account"] == exp_clear for a in stb5)
	if not ok5:
		errors.append(f"Test5: COI PDC STB debits {stb5} expected {exp_clear!r}")
	results["tests"].append(
		{
			"test_id": 5,
			"coi": coi_name,
			"pdc": p5_name,
			"je_refs_after_import": refs_open,
			"je_refs_after_template_save": refs_mid,
			"stb_je": je5,
			"stb_debit_accounts": [a["account"] for a in stb5],
			"passed": refs_open == 0 and refs_mid == 0 and ok5,
		}
	)

	out = {
		"passed": not errors,
		"errors": errors,
		"site": frappe.local.site,
		"results": results,
	}
	print(json.dumps(out, indent=2, default=str))
	if errors:
		raise frappe.ValidationError("PDC template resolver E2E failed:\n" + "\n".join(errors))
	return out
