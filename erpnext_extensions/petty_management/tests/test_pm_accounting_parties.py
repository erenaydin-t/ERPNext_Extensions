# Copyright (c) 2026, Farbod Siyahpoosh and contributors
"""PM Request / PM Clearance accounting — party fields on JE and PE GL."""

from __future__ import annotations

import unittest

import frappe
from frappe.utils import flt, today

from erpnext_extensions.petty_management.services.accounting_party import (
	account_requires_mandatory_party,
	journal_entry_party_for_petty_cash_credit,
)
from erpnext_extensions.petty_management.services.journal_entry_service import (
	build_clearance_je_accounts,
	build_petty_cash_credit_line,
)
from erpnext_extensions.petty_management.tests import test_pm_clearance as pm_ct


def _submit_pi_for_test(pi) -> None:
	bs = frappe.get_single("Buying Settings")
	prev_po = bs.po_required
	bs.po_required = 0
	bs.save(ignore_permissions=True)
	frappe.db.commit()
	try:
		pi.insert(ignore_permissions=True)
		pi.submit()
	except TypeError as exc:
		if "do_not_round_fields" in str(exc):
			raise unittest.SkipTest("Purchase Invoice submit incompatible with this Frappe version") from exc
		raise
	finally:
		bs.po_required = prev_po
		bs.save(ignore_permissions=True)
		frappe.db.commit()


class TestPMAccountingParties(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")
		from erpnext_extensions.petty_management.smoke.final_acceptance_opening_clearance import (
			_patch_pi_round_floats_compat,
		)

		_patch_pi_round_floats_compat()
		pm_ct._ensure_company_context()
		if not pm_ct.COMPANY:
			raise unittest.SkipTest("No Company on site")
		pm_ct._ensure_petty_account()

	def test_payable_petty_credit_includes_employee_party(self):
		emp = pm_ct._make_employee()
		holder = pm_ct._make_holder(emp)
		doc = frappe.new_doc("PM Clearance")
		doc.company = pm_ct.COMPANY
		doc.employee = emp
		doc.holder = holder
		doc.petty_cash_account = pm_ct._ensure_petty_account()
		line = build_petty_cash_credit_line(doc, 500)
		if account_requires_mandatory_party(doc.petty_cash_account):
			self.assertEqual(line.get("party_type"), "Employee")
			self.assertEqual(line.get("party"), emp)
		else:
			self.assertEqual(line.get("party_type"), "Employee")
			self.assertEqual(line.get("party"), emp)

	def test_cash_petty_build_line_includes_employee_party(self):
		emp = pm_ct._make_employee()
		holder = pm_ct._make_holder(emp)
		petty = frappe.db.get_value("PM Holder", holder, "petty_cash_account")
		if not petty:
			self.skipTest("Holder has no petty cash account")
		doc = frappe.new_doc("PM Clearance")
		doc.company = pm_ct.COMPANY
		doc.employee = emp
		doc.holder = holder
		doc.petty_cash_account = petty
		line = build_petty_cash_credit_line(doc, 500)
		self.assertEqual(line.get("party_type"), "Employee", msg=frappe.db.get_value("Account", petty, "account_type"))
		self.assertEqual(line.get("party"), emp)

	def test_cash_petty_on_pm_holder_includes_employee_party(self):
		emp = pm_ct._make_employee()
		holder = pm_ct._make_holder(emp)
		petty = frappe.db.get_value("PM Holder", holder, "petty_cash_account")
		if not petty:
			self.skipTest("Holder has no petty cash account")
		account_type = frappe.db.get_value("Account", petty, "account_type")
		if account_type in ("Receivable", "Payable"):
			self.skipTest("Site petty account is Receivable/Payable; covered by other test")

		doc = frappe.new_doc("PM Clearance")
		doc.company = pm_ct.COMPANY
		doc.employee = emp
		doc.holder = holder
		doc.petty_cash_account = petty
		fields = journal_entry_party_for_petty_cash_credit(
			petty, company=pm_ct.COMPANY, employee=emp, holder=holder
		)
		self.assertEqual(fields.get("party_type"), "Employee")
		self.assertEqual(fields.get("party"), emp)

	def test_generic_cash_account_without_pm_holder_mapping_has_no_party(self):
		parent = pm_ct._petty_parent_account()
		generic = pm_ct._insert_leaf_account("PM Test Orphan Cash Wallet", parent, "Cash")
		emp = pm_ct._make_employee()
		fields = journal_entry_party_for_petty_cash_credit(generic, company=pm_ct.COMPANY, employee=emp)
		self.assertEqual(fields, {})

	def test_clearance_je_supplier_and_employee_parties(self):
		if not pm_ct.BANK_ACCOUNT:
			self.skipTest("No bank account")
		approved = pm_ct._workflow_state_for("PM Clearance", "Approved")
		if not approved:
			self.skipTest("PM Clearance Approved workflow state missing")

		emp = pm_ct._make_employee()
		pm_ct._make_holder(emp)
		from erpnext_extensions.petty_management.tests.test_pm_clearance import _fund_pm_request

		req_name, _pe = _fund_pm_request(emp, 10_000.0)
		pi = pm_ct._make_pi_outstanding(500)
		_submit_pi_for_test(pi)
		cl = frappe.new_doc("PM Clearance")
		cl.company = pm_ct.COMPANY
		cl.employee = emp
		holder = frappe.db.get_value("PM Holder", {"employee": emp, "company": pm_ct.COMPANY}, "name")
		cl.holder = holder
		cl.transaction_date = today()
		pm_ct._append_pm_clearance_detail_row(
			cl,
			{
				"settlement_type": "Purchase Invoice",
				"purchase_invoice": pi.name,
				"allocated_amount": 500,
			},
		)
		cl.append("request_allocations", {"pm_request": req_name, "allocated_amount": 500})
		cl.insert(ignore_permissions=True)
		cl.submit()
		frappe.db.set_value("PM Clearance", cl.name, "workflow_state", approved, update_modified=False)

		from erpnext_extensions.petty_management.services import journal_entry_service as jes

		out = jes.settle_petty_cash(cl.name)
		je = frappe.get_doc("Journal Entry", out["journal_entry"])
		if je.docstatus == 0:
			je.submit()
			frappe.db.commit()
		dr = [r for r in je.accounts if flt(r.debit_in_account_currency) > 0]
		cr = [r for r in je.accounts if flt(r.credit_in_account_currency) > 0]
		self.assertEqual(len(dr), 1)
		self.assertEqual(len(cr), 1)
		self.assertEqual(dr[0].party_type, "Supplier")
		self.assertTrue(dr[0].party)
		emp_party = journal_entry_party_for_petty_cash_credit(
			cr[0].account, company=pm_ct.COMPANY, employee=emp
		)
		if emp_party:
			self.assertEqual(cr[0].party_type, "Employee")
			self.assertEqual(cr[0].party, emp)
		else:
			self.fail("Expected Employee party on petty cash credit line")

		gl = frappe.get_all(
			"GL Entry",
			filters={"voucher_type": "Journal Entry", "voucher_no": je.name, "is_cancelled": 0},
			fields=["account", "party_type", "party", "debit", "credit"],
		)
		petty_gl = [g for g in gl if g.account == cr[0].account and flt(g.credit) > 0]
		self.assertTrue(petty_gl)
		self.assertEqual(petty_gl[0].party_type, "Employee")
		self.assertEqual(petty_gl[0].party, emp)

		accounts_preview = build_clearance_je_accounts(cl)
		cr_preview = accounts_preview[-1]
		self.assertEqual(cr_preview.get("party_type"), cr[0].party_type)
		self.assertEqual(cr_preview.get("party"), cr[0].party)

	def test_pm_request_payment_entry_gl_employee_on_petty_line(self):
		if not pm_ct.BANK_ACCOUNT:
			self.skipTest("No bank account")
		emp = pm_ct._make_employee()
		pm_ct._make_holder(emp)
		req_name, pe_name = pm_ct._fund_pm_request(emp, 2_000.0)
		req = frappe.get_doc("PM Request", req_name)
		pe = frappe.get_doc("Payment Entry", pe_name)
		self.assertEqual(pe.party_type, "Employee")
		self.assertEqual(pe.party, emp)
		self.assertEqual(pe.paid_to, req.petty_cash_account)

		gl = frappe.get_all(
			"GL Entry",
			filters={"voucher_type": "Payment Entry", "voucher_no": pe_name, "is_cancelled": 0},
			fields=["account", "party_type", "party", "debit", "credit"],
		)
		petty_gl = [g for g in gl if g.account == req.petty_cash_account]
		self.assertTrue(petty_gl, msg="No GL on petty cash account")
		for row in petty_gl:
			self.assertEqual(row.party_type, "Employee")
			self.assertEqual(row.party, emp)
