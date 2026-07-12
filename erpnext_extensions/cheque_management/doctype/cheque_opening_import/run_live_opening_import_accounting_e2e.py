"""Live E2E: Cheque Opening Import must not post JEs during import (development.localhost).

bench --site development.localhost execute \\
  erpnext_extensions.cheque_management.doctype.cheque_opening_import.run_live_opening_import_accounting_e2e.run
"""

from __future__ import annotations

import json
import time
from datetime import date, timedelta

import frappe
from frappe.utils import getdate, today

from erpnext_extensions.cheque_management.doctype.cheque_opening_import.cheque_opening_import import (
	import_row,
)
from erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque import (
	_get_pdc_settings_for_company,
)
from erpnext_extensions.cheque_management.pdc_workflow_state_machine import (
	WORKFLOW_REGISTERED,
	WORKFLOW_SENT_TO_BANK,
	normalize_workflow_state_value,
)
from erpnext_extensions.cheque_management.run_live_party_orchestration_e2e import (
	_site_context,
	_unique_cheque_no,
)


def _today():
	return getdate(today())


def _counts(pdc_name: str) -> dict:
	refs = frappe.get_all(
		"PDC Journal Reference",
		filters={"parent": pdc_name, "parenttype": "Post Dated Cheque"},
		fields=["name", "journal_entry", "purpose"],
	)
	jes = {r.journal_entry for r in refs if r.journal_entry}
	return {
		"pdc": pdc_name,
		"journal_reference_count": len(refs),
		"journal_entry_count": len(jes),
		"references": refs,
	}


def _base_receivable_row(ctx: dict, cheque_no: str, workflow_state: str, **extra) -> dict:
	t0 = _today()
	row = {
		"cheque_direction": "Receivable",
		"company": ctx["company"],
		"bank_account": ctx.get("bank_account") or "",
		"cheque_number": cheque_no,
		"cheque_due_date": t0 + timedelta(days=30),
		"cheque_amount": "100",
		"party_type": "Customer",
		"party": ctx["customer"],
		"workflow_state": workflow_state,
		"drawer_bank_name": ctx.get("drawer_bank") or "",
		"received_date": t0,
		"sayad_code": f"OB-{cheque_no}"[:32],
	}
	row.update(extra)
	return row


def _base_payable_row(ctx: dict, cheque_no: str, workflow_state: str, **extra) -> dict:
	t0 = _today()
	row = {
		"cheque_direction": "Payable",
		"company": ctx["company"],
		"bank_account": ctx["bank_account"],
		"cheque_number": cheque_no,
		"cheque_due_date": t0 + timedelta(days=30),
		"cheque_amount": "100",
		"party_type": "Supplier",
		"party": ctx["supplier"],
		"workflow_state": workflow_state,
		"drawer_bank_name": "",
		"received_date": t0,
		"sayad_code": f"OB-{cheque_no}"[:32],
	}
	row.update(extra)
	return row


def _assert_zero(label: str, pdc_name: str, errors: list[str]) -> dict:
	c = _counts(pdc_name)
	if c["journal_entry_count"] != 0 or c["journal_reference_count"] != 0:
		errors.append(
			f"{label}: expected 0 JE/refs, got JE={c['journal_entry_count']} refs={c['journal_reference_count']} {c['references']}"
		)
	return c


def run():
	frappe.set_user("Administrator")
	ctx = _site_context()
	drawer_bank = frappe.db.get_value("Bank", {}, "name", order_by="modified desc")
	if not drawer_bank:
		frappe.throw("No Bank for drawer_bank_name")
	ctx["drawer_bank"] = drawer_bank

	settings = _get_pdc_settings_for_company(ctx["company"])
	if not settings:
		frappe.throw("PDC Settings missing")

	errors: list[str] = []
	results: list[dict] = []
	t0 = _today()
	row_no = int(time.time()) % 100000

	# Test 1 — Receivable Registered
	row_no += 1
	chq1 = _unique_cheque_no("OI-R-REG")
	pdc1 = import_row(row_no, _base_receivable_row(ctx, chq1, "Registered"))
	results.append(
		{"test": 1, "label": "import_receivable_registered", "counts": _assert_zero("test1", pdc1, errors)}
	)

	# Test 2 — Receivable Sent To Bank
	row_no += 1
	chq2 = _unique_cheque_no("OI-R-STB")
	pdc2 = import_row(
		row_no,
		_base_receivable_row(
			ctx,
			chq2,
			"Sent to Bank",
			sent_to_bank_date=t0,
		),
	)
	results.append(
		{"test": 2, "label": "import_receivable_sent_to_bank", "counts": _assert_zero("test2", pdc2, errors)}
	)

	# Test 3 — Receivable Cleared
	row_no += 1
	chq3 = _unique_cheque_no("OI-R-CLR")
	pdc3 = import_row(
		row_no,
		_base_receivable_row(
			ctx,
			chq3,
			"Cleared",
			cleared_date=t0,
		),
	)
	results.append(
		{"test": 3, "label": "import_receivable_cleared", "counts": _assert_zero("test3", pdc3, errors)}
	)

	# Test 4 — Payable Registered
	row_no += 1
	chq4 = _unique_cheque_no("OI-P-REG")
	pdc4 = import_row(row_no, _base_payable_row(ctx, chq4, "Registered"))
	results.append(
		{"test": 4, "label": "import_payable_registered", "counts": _assert_zero("test4", pdc4, errors)}
	)

	# Test 5 — Payable Cleared
	row_no += 1
	chq5 = _unique_cheque_no("OI-P-CLR")
	pdc5 = import_row(
		row_no,
		_base_payable_row(
			ctx,
			chq5,
			"Cleared",
			handover_date=t0,
			cleared_date=t0,
		),
	)
	results.append(
		{"test": 5, "label": "import_payable_cleared", "counts": _assert_zero("test5", pdc5, errors)}
	)

	# Test 6 — Import Registered then live Registered → Sent To Bank
	row_no += 1
	chq6 = _unique_cheque_no("OI-R-LIVE")
	pdc6 = import_row(row_no, _base_receivable_row(ctx, chq6, "Registered"))
	after_import = _counts(pdc6)
	if after_import["journal_entry_count"] != 0:
		errors.append(f"test6: after import expected 0 JE, got {after_import}")

	pdc_doc = frappe.get_doc("Post Dated Cheque", pdc6)
	pdc_doc.sent_to_bank_date = t0
	pdc_doc.workflow_state = WORKFLOW_SENT_TO_BANK
	pdc_doc.flags.ignore_validate_update_after_submit = True
	pdc_doc.save(ignore_permissions=True)
	frappe.db.commit()

	after_stb = _counts(pdc6)
	if after_stb["journal_entry_count"] != 1 or after_stb["journal_reference_count"] != 1:
		errors.append(f"test6: after STB expected 1 JE + 1 ref, got {after_stb}")
	results.append(
		{
			"test": 6,
			"label": "import_then_live_sent_to_bank",
			"after_import": after_import,
			"after_sent_to_bank": after_stb,
		}
	)

	# Test 7 — Normal non-import Draft → Registered
	chq7 = _unique_cheque_no("OI-NORM")
	doc = frappe.new_doc("Post Dated Cheque")
	doc.cheque_direction = "Receivable"
	doc.company = ctx["company"]
	doc.party_type = "Customer"
	doc.party = ctx["customer"]
	doc.cheque_no = chq7
	doc.cheque_due_date = t0 + timedelta(days=30)
	doc.cheque_amount = 100.0
	doc.drawer_bank_name = drawer_bank
	doc.bank_account = ctx.get("bank_account")
	doc.workflow_state = normalize_workflow_state_value(None)
	doc.allocation_mode = "direct_settlement"
	doc.sayad_code = f"SAYAD-{chq7}"[:32]
	doc.sayad_registered = 1
	doc.is_opening_import = 0
	doc.insert(ignore_permissions=True)
	doc.received_date = t0
	doc.workflow_state = WORKFLOW_REGISTERED
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	norm = _counts(doc.name)
	if norm["journal_entry_count"] != 1 or norm["journal_reference_count"] != 1:
		errors.append(f"test7: normal register expected 1 JE, got {norm}")
	results.append({"test": 7, "label": "normal_draft_to_registered", "counts": norm})

	out = {"passed": not errors, "errors": errors, "results": results}
	print(json.dumps(out, indent=2, default=str))
	if errors:
		frappe.throw("Opening import accounting E2E failed:\n" + "\n".join(errors))
	return out
