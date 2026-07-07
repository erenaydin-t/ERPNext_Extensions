# Copyright (c) 2026, ERPNext Extensions contributors
"""Prove can_cancel_document override does not change non–Post Dated Cheque behavior."""

from __future__ import annotations

import unittest

import frappe
from frappe.exceptions import DoesNotExistError, ValidationError

from erpnext_extensions.cheque_management.pdc_direct_cancel_policy import (
	can_cancel_document as ext_can_cancel_document,
)
from erpnext_extensions.cheque_management.tests.test_pdc_direct_cancel import (
	_make_submitted_registered_payable,
)
from erpnext_extensions.cheque_management.utils.pdc_import_cleanup import (
	unlink_opening_import_and_delete_pdc,
)
from erpnext_extensions.cheque_management.tests.test_pdc_import_cleanup import (
	_attach_coi_import_link,
	_create_draft_receivable_pdc,
)
from erpnext_extensions.cheque_management.run_live_party_orchestration_e2e import (
	_site_context,
	_unique_cheque_no,
)
from frappe.model.workflow import can_cancel_document as frappe_can_cancel_document


# ERPNext / common desk doctypes (workflow or standard cancel toolbar).
_NON_PDC_DOCTYPES = (
	"Sales Invoice",
	"Purchase Invoice",
	"Payment Entry",
	"Journal Entry",
	"Stock Entry",
	"Delivery Note",
	"Purchase Receipt",
	"Expense Claim",
	"Asset",
	"Loan",
	"PM Request",
	"PM Clearance",
)


def _compare_can_cancel(doctype: str) -> tuple[bool, str]:
	"""Return (match, detail) comparing extension wrapper vs Frappe native."""
	try:
		ext = ext_can_cancel_document(doctype)
	except Exception as ext_exc:
		try:
			frappe_can_cancel_document(doctype)
			return False, f"ext raised {type(ext_exc).__name__}, frappe succeeded"
		except Exception as frappe_exc:
			if type(ext_exc) is type(frappe_exc):
				return True, f"both raised {type(ext_exc).__name__}"
			return False, f"ext={type(ext_exc).__name__} frappe={type(frappe_exc).__name__}"

	try:
		frappe_val = frappe_can_cancel_document(doctype)
	except Exception as frappe_exc:
		return False, f"ext={ext!r} frappe raised {type(frappe_exc).__name__}"
	if ext == frappe_val:
		return True, repr(ext)
	return False, f"ext={ext!r} frappe={frappe_val!r}"


class TestCanCancelDocumentCrossDoctypeRegression(unittest.TestCase):
	def test_pdc_forced_false(self):
		self.assertFalse(ext_can_cancel_document("Post Dated Cheque"))

	def test_non_pdc_matches_frappe_native(self):
		mismatches = []
		for dt in _NON_PDC_DOCTYPES:
			ok, detail = _compare_can_cancel(dt)
			if not ok:
				mismatches.append(f"{dt}: {detail}")
		self.assertFalse(mismatches, "\n".join(mismatches))

	def test_hook_override_registered(self):
		overrides = frappe.get_hooks("override_whitelisted_methods") or {}
		target = overrides.get("frappe.model.workflow.can_cancel_document")
		if isinstance(target, list):
			target = target[-1]
		self.assertEqual(
			target,
			"erpnext_extensions.cheque_management.pdc_direct_cancel_policy.can_cancel_document",
		)


class TestStandardDoctypeCancelRegression(unittest.TestCase):
	"""Submit + cancel on a Journal Entry (no PDC hooks on JE)."""

	def setUp(self):
		frappe.set_user("Administrator")

	def test_journal_entry_submit_and_cancel(self):
		company = frappe.db.get_value("Company", {}, "name", order_by="creation asc")
		if not company:
			self.skipTest("no company")
		je = frappe.new_doc("Journal Entry")
		je.voucher_type = "Journal Entry"
		je.company = company
		je.posting_date = frappe.utils.today()
		cash = frappe.db.get_value(
			"Account",
			{"company": company, "account_type": "Cash", "is_group": 0},
			"name",
			order_by="creation asc",
		)
		exp = frappe.db.get_value(
			"Account",
			{"company": company, "root_type": "Expense", "is_group": 0},
			"name",
			order_by="creation asc",
		)
		if not cash or not exp:
			self.skipTest("need cash and expense accounts")
		je.append("accounts", {"account": cash, "debit_in_account_currency": 1})
		je.append("accounts", {"account": exp, "credit_in_account_currency": 1})
		je.insert(ignore_permissions=True)
		je.submit()
		self.assertEqual(je.docstatus, 1)
		je.cancel()
		self.assertEqual(je.docstatus, 2)
		frappe.delete_doc("Journal Entry", je.name, force=True, ignore_permissions=True)
		frappe.db.commit()

	def test_pdc_cancel_still_blocked_after_je_cancel(self):
		doc = _make_submitted_registered_payable()
		with self.assertRaises(ValidationError) as ctx:
			frappe.get_doc("Post Dated Cheque", doc.name).cancel()
		self.assertIn("Rollback Workflow State", str(ctx.exception))

	def test_delete_imported_pdc_still_cancels_internally(self):
		ctx = _site_context()
		chq = _unique_cheque_no("UT-REG-CAN")
		pdc = _create_draft_receivable_pdc(ctx, chq)
		_attach_coi_import_link(pdc)
		frappe.db.commit()
		out = unlink_opening_import_and_delete_pdc(pdc, reason="cross-doctype regression")
		self.assertTrue(out["ok"])
		self.assertFalse(frappe.db.exists("Post Dated Cheque", pdc))
