# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

"""Integration: Registered → Assigned Debt Purchase → rollback → Registered."""

from __future__ import annotations

import unittest
from datetime import timedelta

import frappe
from frappe.utils import flt, getdate, random_string, today

from erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque import (
	_get_pdc_settings_for_company,
	get_default_party_accounts,
	resolve_pdc_accounts_for_journal,
)
from erpnext_extensions.cheque_management.pdc_workflow_rollback import (
	get_rollback_target_states,
	rollback_workflow_state,
)
from erpnext_extensions.cheque_management.pdc_workflow_state_machine import (
	WORKFLOW_ASSIGNED_DEBT_PURCHASE,
	WORKFLOW_DRAFT,
	WORKFLOW_REGISTERED,
	normalize_workflow_state_value,
)
from erpnext_extensions.facility_management.facility_e2e_context import ensure_bank_master


PURPOSE_ASSIGNMENT = "Debt Purchase Assignment"


def _pick_company() -> str:
	row = frappe.db.sql(
		"""
		SELECT c.name
		FROM `tabCompany` c
		WHERE c.name NOT LIKE '\\_Test%%'
		  AND EXISTS (SELECT 1 FROM `tabAccount` a WHERE a.company = c.name AND a.is_group = 0 LIMIT 1)
		ORDER BY c.creation ASC
		LIMIT 1
		""",
		as_list=True,
	)
	if row:
		return row[0][0]
	company = frappe.db.get_value("Company", {}, "name", order_by="creation asc")
	if not company:
		frappe.throw("No Company")
	return company


def _ensure_dpic(company: str) -> str:
	settings_name = frappe.db.get_value("PDC Settings", {"company": company}, "name") or company
	settings = frappe.get_doc("PDC Settings", settings_name) if frappe.db.exists("PDC Settings", settings_name) else None
	if settings and (settings.default_debt_purchase_in_collection_account or "").strip():
		return settings.default_debt_purchase_in_collection_account
	parent = frappe.db.get_value(
		"Account",
		{"company": company, "is_group": 1, "root_type": "Asset"},
		"name",
		order_by="lft asc",
	)
	acc_name = "E2E Debt Purchase In Collection"
	exists = frappe.db.get_value("Account", {"company": company, "account_name": acc_name}, "name")
	if not exists:
		acc = frappe.new_doc("Account")
		acc.company = company
		acc.parent_account = parent
		acc.account_name = acc_name
		acc.is_group = 0
		acc.insert(ignore_permissions=True)
		exists = acc.name
	if not settings:
		doc = frappe.new_doc("PDC Settings")
		doc.company = company
		doc.name = settings_name
		doc.default_debt_purchase_in_collection_account = exists
		doc.insert(ignore_permissions=True)
	else:
		settings.default_debt_purchase_in_collection_account = exists
		settings.save(ignore_permissions=True)
	return exists


def _refs(pdc_name: str, *, purpose: str | None = None) -> list[dict]:
	filters: dict = {"parent": pdc_name, "parenttype": "Post Dated Cheque"}
	if purpose:
		filters["purpose"] = purpose
	return frappe.get_all(
		"PDC Journal Reference",
		filters=filters,
		fields=["name", "journal_entry", "purpose", "pdc_transition_key"],
		order_by="idx asc",
	)


class TestDebtPurchaseAssignmentRollback(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")
		cls.company = _pick_company()
		cls.dpic = _ensure_dpic(cls.company)
		cls.customer = frappe.db.get_value("Customer", {"disabled": 0}, "name", order_by="modified desc")
		if not cls.customer:
			raise unittest.SkipTest("No Customer")
		cls.bank_account = frappe.db.get_value(
			"Bank Account",
			{"company": cls.company, "disabled": 0},
			"name",
			order_by="modified desc",
		)
		if not cls.bank_account:
			raise unittest.SkipTest("No Bank Account")
		cls.settings = _get_pdc_settings_for_company(cls.company)
		if not cls.settings or not cls.settings.default_cheques_in_hand_account:
			raise unittest.SkipTest("PDC Settings / Cheques in Hand missing")
		frappe.db.commit()

	def _apply_action(self, doc, action: str):
		from frappe.model.workflow import apply_workflow

		return apply_workflow(doc, action)

	def _new_assigned_pdc(self, *, amount: float = 1000.0) -> tuple[str, str]:
		"""Returns (pdc_name, assignment_je_name). Uses Desk workflow actions so docstatus=1."""
		acc = get_default_party_accounts("Customer", self.customer, self.company, "Receivable") or {}
		doc = frappe.new_doc("Post Dated Cheque")
		doc.cheque_direction = "Receivable"
		doc.company = self.company
		doc.party_type = "Customer"
		doc.party = self.customer
		doc.cheque_no = f"DP-RB-{random_string(8)}"
		doc.cheque_due_date = getdate(today()) + timedelta(days=30)
		doc.cheque_amount = amount
		doc.received_date = today()
		drawer_bank = frappe.db.get_value("Bank", {}, "name", order_by="modified desc") or ensure_bank_master()
		doc.drawer_bank_name = drawer_bank
		doc.bank_account = self.bank_account
		doc.account_paid_to = acc.get("account_paid_to") or self.settings.default_cheques_in_hand_account
		doc.account_paid_from = acc.get("account_paid_from")
		doc.workflow_state = WORKFLOW_DRAFT
		doc.allocation_mode = "direct_settlement"
		doc.sayad_code = f"SAYAD-{doc.cheque_no}"[:32]
		doc.sayad_registered = 1
		doc.insert(ignore_permissions=True)
		frappe.db.commit()

		doc = frappe.get_doc("Post Dated Cheque", doc.name)
		doc = self._apply_action(doc, "Register Cheque")
		doc.reload()
		self.assertEqual(doc.docstatus, 1)
		self.assertEqual(normalize_workflow_state_value(doc.workflow_state), WORKFLOW_REGISTERED)
		frappe.db.commit()

		doc = self._apply_action(doc, "Assign for Debt Purchase")
		doc.reload()
		self.assertEqual(
			normalize_workflow_state_value(doc.workflow_state), WORKFLOW_ASSIGNED_DEBT_PURCHASE
		)
		frappe.db.commit()

		assign_refs = _refs(doc.name, purpose=PURPOSE_ASSIGNMENT)
		self.assertEqual(len(assign_refs), 1, assign_refs)
		return doc.name, assign_refs[0]["journal_entry"]

	def test_assign_then_rollback_to_registered(self):
		pdc_name, assign_je = self._new_assigned_pdc(amount=1500.0)
		pdc = frappe.get_doc("Post Dated Cheque", pdc_name)
		roles = resolve_pdc_accounts_for_journal(pdc)
		dpic = roles["debt_purchase_in_collection"]
		cih = (pdc.account_paid_to or "").strip() or roles["cheques_in_hand"]

		# Assignment JE matrix
		rows = frappe.get_all(
			"Journal Entry Account",
			filters={"parent": assign_je},
			fields=[
				"account",
				"debit_in_account_currency",
				"credit_in_account_currency",
				"party_type",
				"party",
			],
			order_by="idx asc",
		)
		self.assertEqual(len(rows), 2)
		dr = next(r for r in rows if flt(r.debit_in_account_currency) > 0)
		cr = next(r for r in rows if flt(r.credit_in_account_currency) > 0)
		self.assertEqual(dr.account, dpic)
		self.assertEqual(cr.account, cih)
		self.assertAlmostEqual(flt(dr.debit_in_account_currency), 1500.0)
		self.assertAlmostEqual(flt(cr.credit_in_account_currency), 1500.0)
		for r in rows:
			self.assertFalse(r.party_type)
			self.assertFalse(r.party)

		assign_refs = _refs(pdc_name, purpose=PURPOSE_ASSIGNMENT)
		self.assertEqual(len(assign_refs), 1)
		self.assertEqual(assign_refs[0]["journal_entry"], assign_je)
		self.assertFalse(pdc.debt_purchase_facility)
		self.assertFalse(pdc.debt_purchase_repayment)

		targets = get_rollback_target_states(pdc_name)
		self.assertIn(WORKFLOW_REGISTERED, targets)

		result = rollback_workflow_state(
			pdc_name, WORKFLOW_REGISTERED, "DP assignment rollback integration test"
		)
		self.assertTrue(result)

		pdc.reload()
		self.assertEqual(normalize_workflow_state_value(pdc.workflow_state), WORKFLOW_REGISTERED)
		self.assertEqual(frappe.db.get_value("Journal Entry", assign_je, "docstatus"), 2)
		self.assertEqual(frappe.db.count("GL Entry", {"voucher_no": assign_je, "is_cancelled": 0}), 0)
		self.assertEqual(len(_refs(pdc_name, purpose=PURPOSE_ASSIGNMENT)), 0)
		# Receive reference from Draft→Registered must remain
		self.assertTrue(_refs(pdc_name))
		self.assertFalse(pdc.debt_purchase_facility)
		self.assertFalse(pdc.debt_purchase_repayment)
		# No duplicate assignment refs
		self.assertEqual(len(_refs(pdc_name, purpose=PURPOSE_ASSIGNMENT)), 0)

		# Second rollback to Registered must fail safely (already Registered)
		with self.assertRaises(Exception):
			rollback_workflow_state(
				pdc_name, WORKFLOW_REGISTERED, "second rollback should fail"
			)
		frappe.db.rollback()
		pdc.reload()
		self.assertEqual(normalize_workflow_state_value(pdc.workflow_state), WORKFLOW_REGISTERED)
		self.assertEqual(len(_refs(pdc_name, purpose=PURPOSE_ASSIGNMENT)), 0)


if __name__ == "__main__":
	unittest.main()
