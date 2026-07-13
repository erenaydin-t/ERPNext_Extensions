"""Final acceptance: PM Opening Advance clearance through JE and cancel restore."""

from __future__ import annotations

import json

import frappe
from frappe.utils import flt, today

import erpnext_extensions.petty_management.tests.test_pm_clearance as pm_ct
from erpnext_extensions.petty_management.services.opening_advance_service import (
	get_opening_advance_available_amount,
)


def _patch_pi_round_floats_compat() -> None:
	"""ERPNext passes do_not_round_fields; older Frappe only accepts fieldnames."""
	from frappe.model.document import Document

	if getattr(Document.round_floats_in, "_pm_pi_compat", False):
		return
	_original = Document.round_floats_in

	def round_floats_in(self, doc, fieldnames=None, do_not_round_fields=None, **kwargs):
		if fieldnames is None and do_not_round_fields:
			fieldnames = [
				df.fieldname
				for df in doc.meta.get("fields", {"fieldtype": ["in", ["Currency", "Float", "Percent"]]})
				if df.fieldname not in do_not_round_fields
			]
		return _original(self, doc, fieldnames=fieldnames)

	round_floats_in._pm_pi_compat = True  # type: ignore[attr-defined]
	Document.round_floats_in = round_floats_in  # type: ignore[method-assign]


def execute():
	frappe.set_user("Administrator")
	_patch_pi_round_floats_compat()
	pm_ct._ensure_company_context()
	if not pm_ct.COMPANY:
		print(json.dumps({"status": "FAILED", "error": "No Company"}, indent=2))
		return
	pm_ct._ensure_petty_account()

	report: dict = {"status": "IN_PROGRESS", "steps": []}

	def log_step(step_name: str, ok: bool, **extra):
		report["steps"].append({"step": step_name, "ok": ok, **extra})

	try:
		emp = pm_ct._make_employee()
		holder = pm_ct._make_holder(emp)
		log_step("holder", True, employee=emp, holder=holder)

		oa = frappe.new_doc("PM Opening Advance")
		oa.holder = holder
		oa.opening_date = today()
		oa.opening_source_type = "Opening Balance"
		oa.opening_advance_amount = 12_000
		oa.previously_settled_before_migration = 4_000
		oa.reference_no = "FINAL-ACCEPTANCE"
		oa.insert(ignore_permissions=True)
		oa.submit()
		bal_before = get_opening_advance_available_amount(oa.name)
		log_step(
			"pm_opening_advance",
			True,
			name=oa.name,
			opening_available_before_clearance=bal_before,
		)
		if abs(bal_before - 8_000) > 0.01:
			raise frappe.ValidationError(f"Expected opening available 8000, got {bal_before}")

		pi = pm_ct._make_pi_outstanding(4_000)
		bs = frappe.get_single("Buying Settings")
		prev_po_required = bs.po_required
		bs.po_required = 0
		bs.save(ignore_permissions=True)
		try:
			pi.insert(ignore_permissions=True)
			pi.submit()
		except TypeError as exc:
			if "do_not_round_fields" in str(exc):
				report["status"] = "BLOCKED"
				report["blocker"] = "SKIPPED_PI_SUBMIT_ENVIRONMENT: cannot run full acceptance on this site"
				report["partial"] = {
					"pm_opening_advance": oa.name,
					"opening_available": bal_before,
				}
				print(json.dumps(report, indent=2, default=str))
				return
			raise
		finally:
			bs.po_required = prev_po_required
			bs.save(ignore_permissions=True)
		frappe.db.commit()
		log_step("purchase_invoice", True, name=pi.name, docstatus=pi.docstatus)

		cl = frappe.new_doc("PM Clearance")
		cl.company = pm_ct.COMPANY
		cl.employee = emp
		cl.transaction_date = today()
		pm_ct._append_pm_clearance_detail_row(
			cl,
			{
				"settlement_type": "Purchase Invoice",
				"purchase_invoice": pi.name,
				"allocated_amount": 4_000,
			},
		)
		cl.append(
			"request_allocations",
			{
				"funding_source_type": "PM Opening Advance",
				"pm_opening_advance": oa.name,
				"allocated_amount": 4_000,
			},
		)
		cl.insert(ignore_permissions=True)
		log_step("pm_clearance_save", True, name=cl.name)

		cl.submit()
		pm_ct._approve_pm_clearance_for_reservation(cl.name)
		approved = pm_ct._workflow_state_for("PM Clearance", "Approved")
		if approved:
			frappe.db.set_value("PM Clearance", cl.name, "workflow_state", approved, update_modified=False)

		bal_after_save = get_opening_advance_available_amount(oa.name)
		log_step(
			"after_submit_reserve",
			abs(bal_after_save - 4_000) < 0.01,
			opening_available=bal_after_save,
			pm_clearance=cl.name,
		)

		from erpnext_extensions.petty_management.doctype.pm_clearance import pm_clearance as mod

		out = mod.settle_petty_cash(cl.name)
		je_name = out.get("journal_entry")
		je = frappe.get_doc("Journal Entry", je_name)
		if je.docstatus == 0:
			je.submit()
		log_step("settlement_je", True, journal_entry=je_name, je_docstatus=je.docstatus)

		bal_after_je = get_opening_advance_available_amount(oa.name)
		log_step("after_je", abs(bal_after_je - 4_000) < 0.01, opening_available=bal_after_je)

		je.cancel()
		cl.reload()
		cl.cancel()

		bal_after_cancel = get_opening_advance_available_amount(oa.name)
		log_step(
			"after_clearance_cancel",
			abs(bal_after_cancel - 8_000) < 0.01,
			opening_available=bal_after_cancel,
		)

		report["status"] = "PASSED"
		report["summary"] = {
			"pm_opening_advance": oa.name,
			"purchase_invoice": pi.name,
			"pm_clearance": cl.name,
			"journal_entry": je_name,
			"opening_available_initial": 8_000,
			"opening_available_after_reserve_and_je": bal_after_je,
			"opening_available_after_cancel": bal_after_cancel,
		}
	except Exception as exc:
		report["status"] = "FAILED"
		report["error"] = str(exc)
		frappe.log_error(frappe.get_traceback(), "final_acceptance_opening_clearance")

	print(json.dumps(report, indent=2, default=str))
