# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

"""Integration: Assigned Debt Purchase has no rollback; Bounce restores DPIC."""

from __future__ import annotations

import unittest
from datetime import timedelta

import frappe
from frappe.model.workflow import get_transitions
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
	WORKFLOW_BOUNCED,
	WORKFLOW_CLEARED,
	WORKFLOW_DEBT_PURCHASE_SETTLED,
	WORKFLOW_DRAFT,
	WORKFLOW_REGISTERED,
	WORKFLOW_RETURNED,
	WORKFLOW_SENT_TO_BANK,
	get_pdc_workflow_transition_validation_error,
	normalize_workflow_state_value,
)
from erpnext_extensions.facility_management.facility_e2e_context import ensure_bank_master


PURPOSE_ASSIGNMENT = "Debt Purchase Assignment"
PURPOSE_BOUNCE = "Returned"  # canonical bounce purpose (same as Sent to Bank → Bounced)


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


def _account_balance(account: str, company: str) -> float:
	row = frappe.db.sql(
		"""
		SELECT COALESCE(SUM(debit) - SUM(credit), 0)
		FROM `tabGL Entry`
		WHERE account = %s AND company = %s AND is_cancelled = 0
		""",
		(account, company),
	)
	return flt(row[0][0] if row else 0)


class TestDebtPurchaseAssignedTransitions(unittest.TestCase):
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
		# Ensure site workflow matches Bounce-from-Assigned policy.
		from erpnext_extensions.patches.post_model_sync.ensure_debt_purchase_pdc_workflow import (
			execute as sync_dp_workflow,
		)

		sync_dp_workflow()
		frappe.db.commit()

	def _apply_action(self, doc, action: str):
		from frappe.model.workflow import apply_workflow

		return apply_workflow(doc, action)

	@staticmethod
	def _workflow_actions(doc) -> set[str]:
		return {t.get("action") or "" for t in get_transitions(doc) if t.get("action")}

	@staticmethod
	def _workflow_next_states(doc) -> set[str]:
		return {t.get("next_state") or "" for t in get_transitions(doc) if t.get("next_state")}

	def _new_receivable_draft(self, *, amount: float = 1000.0, cheque_prefix: str = "DP-RB"):
		acc = get_default_party_accounts("Customer", self.customer, self.company, "Receivable") or {}
		doc = frappe.new_doc("Post Dated Cheque")
		doc.cheque_direction = "Receivable"
		doc.company = self.company
		doc.party_type = "Customer"
		doc.party = self.customer
		doc.cheque_no = f"{cheque_prefix}-{random_string(8)}"
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
		return frappe.get_doc("Post Dated Cheque", doc.name)

	def _new_assigned_pdc(self, *, amount: float = 1000.0) -> tuple[str, str]:
		"""Returns (pdc_name, assignment_je_name). Uses Desk workflow actions so docstatus=1."""
		doc = self._new_receivable_draft(amount=amount, cheque_prefix="DP-RB")
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

	def _new_sent_to_bank_pdc(self, *, amount: float = 1000.0) -> str:
		doc = self._new_receivable_draft(amount=amount, cheque_prefix="DP-STB")
		doc = self._apply_action(doc, "Register Cheque")
		doc.reload()
		doc.sent_to_bank_date = today()
		doc.save(ignore_permissions=True)
		frappe.db.commit()
		doc = frappe.get_doc("Post Dated Cheque", doc.name)
		doc = self._apply_action(doc, "Send to Bank")
		doc.reload()
		self.assertEqual(normalize_workflow_state_value(doc.workflow_state), WORKFLOW_SENT_TO_BANK)
		frappe.db.commit()
		return doc.name

	def test_assigned_has_no_rollback_targets(self):
		pdc_name, _assign_je = self._new_assigned_pdc(amount=1200.0)
		targets = get_rollback_target_states(pdc_name)
		self.assertEqual(targets, [])
		self.assertNotIn(WORKFLOW_REGISTERED, targets)

		with self.assertRaises(Exception):
			rollback_workflow_state(pdc_name, WORKFLOW_REGISTERED, "must fail — no rollback from Assigned DP")
		frappe.db.rollback()

		pdc = frappe.get_doc("Post Dated Cheque", pdc_name)
		self.assertEqual(
			normalize_workflow_state_value(pdc.workflow_state), WORKFLOW_ASSIGNED_DEBT_PURCHASE
		)
		self.assertEqual(len(_refs(pdc_name, purpose=PURPOSE_ASSIGNMENT)), 1)

	def test_assigned_forbidden_desk_transitions(self):
		"""Registered / Returned / Cleared / Settled rejected from Assigned DP."""
		for target in (
			WORKFLOW_REGISTERED,
			WORKFLOW_RETURNED,
			WORKFLOW_CLEARED,
			WORKFLOW_DEBT_PURCHASE_SETTLED,
		):
			err = get_pdc_workflow_transition_validation_error(
				"Receivable", WORKFLOW_ASSIGNED_DEBT_PURCHASE, target
			)
			self.assertIsNotNone(err, target)

	def test_assigned_dp_workflow_action_visibility(self):
		"""Desk actions from Assigned DP: Bounce only; no Return/Clear/Register/Rollback."""
		pdc_name, _je = self._new_assigned_pdc(amount=1100.0)
		pdc = frappe.get_doc("Post Dated Cheque", pdc_name)
		actions = self._workflow_actions(pdc)
		next_states = self._workflow_next_states(pdc)

		self.assertIn("Bounce Cheque", actions)
		self.assertEqual(actions, {"Bounce Cheque"}, actions)
		self.assertEqual(next_states, {WORKFLOW_BOUNCED}, next_states)

		forbidden_actions = {
			"Return Cheque",
			"Return Debt Purchase Cheque",
			"Clear Cheque",
			"Register Cheque",
			"Send to Bank",
			"Rollback",
			"Rollback Workflow",
		}
		self.assertFalse(actions & forbidden_actions, actions)
		for state in (WORKFLOW_REGISTERED, WORKFLOW_RETURNED, WORKFLOW_CLEARED, WORKFLOW_DEBT_PURCHASE_SETTLED):
			self.assertNotIn(state, next_states)

		# Rollback is not a workflow action and has no targets from Assigned DP.
		self.assertEqual(get_rollback_target_states(pdc_name), [])

	def test_sent_to_bank_still_exposes_bounce_cheque(self):
		"""Non–Debt Purchase Receivable path: Sent to Bank still offers Bounce Cheque."""
		pdc_name = self._new_sent_to_bank_pdc(amount=900.0)
		pdc = frappe.get_doc("Post Dated Cheque", pdc_name)
		actions = self._workflow_actions(pdc)
		self.assertIn("Bounce Cheque", actions)
		self.assertIn(WORKFLOW_BOUNCED, self._workflow_next_states(pdc))

	def test_assign_then_bounce_debits_protested_clears_dpic_party_free(self):
		amount = 1750.0
		pdc_name, assign_je = self._new_assigned_pdc(amount=amount)
		pdc = frappe.get_doc("Post Dated Cheque", pdc_name)
		roles = resolve_pdc_accounts_for_journal(pdc)
		dpic = roles["debt_purchase_in_collection"]
		cih = (pdc.account_paid_to or "").strip() or roles["cheques_in_hand"]
		protested = roles["protested"]
		self.assertTrue(protested, "PDC Settings Default Protested Account required for DP bounce")

		dpic_before = _account_balance(dpic, self.company)

		# Assignment JE: Dr DPIC / Cr CIH, with Party
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
		pdc_party = frappe.db.get_value("Post Dated Cheque", pdc_name, ["party_type", "party"], as_dict=True)
		for r in rows:
			self.assertEqual(r.party_type, pdc_party.party_type)
			self.assertEqual(r.party, pdc_party.party)

		pdc.bounced_date = today()
		pdc.save(ignore_permissions=True)
		frappe.db.commit()
		pdc = frappe.get_doc("Post Dated Cheque", pdc_name)
		pdc = self._apply_action(pdc, "Bounce Cheque")
		pdc.reload()
		self.assertEqual(normalize_workflow_state_value(pdc.workflow_state), WORKFLOW_BOUNCED)
		frappe.db.commit()

		bounce_refs = [
			r
			for r in _refs(pdc_name)
			if r.get("pdc_transition_key")
			and "Assigned to Bank for Debt Purchase|Bounced" in (r.get("pdc_transition_key") or "")
		]
		self.assertEqual(len(bounce_refs), 1, bounce_refs)
		bounce_je = bounce_refs[0]["journal_entry"]
		self.assertEqual(bounce_refs[0]["purpose"], PURPOSE_BOUNCE)

		bounce_rows = frappe.get_all(
			"Journal Entry Account",
			filters={"parent": bounce_je},
			fields=[
				"account",
				"debit_in_account_currency",
				"credit_in_account_currency",
				"party_type",
				"party",
			],
			order_by="idx asc",
		)
		self.assertEqual(len(bounce_rows), 2)
		dr = next(r for r in bounce_rows if flt(r.debit_in_account_currency) > 0)
		cr = next(r for r in bounce_rows if flt(r.credit_in_account_currency) > 0)
		self.assertEqual(dr.account, protested)
		self.assertEqual(cr.account, dpic)
		self.assertNotEqual(dr.account, cih)
		self.assertAlmostEqual(flt(dr.debit_in_account_currency), amount)
		self.assertAlmostEqual(flt(cr.credit_in_account_currency), amount)
		pdc_party = frappe.db.get_value("Post Dated Cheque", pdc_name, ["party_type", "party"], as_dict=True)
		for r in bounce_rows:
			self.assertEqual(r.party_type, pdc_party.party_type)
			self.assertEqual(r.party, pdc_party.party)
			self.assertNotEqual(r.account, cih)

		dpic_after = _account_balance(dpic, self.company)
		self.assertAlmostEqual(dpic_after, dpic_before - amount, places=3)


if __name__ == "__main__":
	unittest.main()
