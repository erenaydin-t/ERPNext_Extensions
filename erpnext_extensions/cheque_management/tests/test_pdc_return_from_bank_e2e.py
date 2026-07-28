# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

"""Backend E2E: Return from Bank cycles, opening balance, and Party JE→GL."""

from __future__ import annotations

import time
import unittest
from collections import defaultdict
from datetime import timedelta

import frappe
from frappe.model.workflow import apply_workflow
from frappe.utils import flt, getdate, today

from erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque import (
	_get_pdc_settings_for_company,
	get_default_party_accounts,
)
from erpnext_extensions.cheque_management.pdc_journal_entry_service import post_pdc_transition_journal_entry
from erpnext_extensions.cheque_management.pdc_workflow_state_machine import (
	WORKFLOW_BOUNCED,
	WORKFLOW_CLEARED,
	WORKFLOW_DRAFT,
	WORKFLOW_REGISTERED,
	WORKFLOW_SENT_TO_BANK,
	get_pdc_workflow_transition_validation_error,
	is_workflow_transition_allowed,
	normalize_workflow_state_value,
)
from erpnext_extensions.cheque_management.pdc_workflow_to_cheque_status import (
	map_workflow_state_to_cheque_status,
)


def _company() -> str:
	return frappe.db.get_value("Company", {}, "name", order_by="creation asc")


def _party_map_je(je: str) -> dict:
	m = defaultdict(set)
	for r in frappe.get_all(
		"Journal Entry Account",
		filters={"parent": je},
		fields=["account", "party_type", "party", "debit_in_account_currency", "credit_in_account_currency"],
	):
		if flt(r.debit_in_account_currency) or flt(r.credit_in_account_currency):
			m[r.account].add((r.party_type or None, r.party or None))
	return {k: sorted(v) for k, v in m.items()}


def _party_map_gl(je: str) -> dict:
	m = defaultdict(set)
	for r in frappe.db.sql(
		"""
		SELECT account, party_type, party FROM `tabGL Entry`
		WHERE voucher_type='Journal Entry' AND voucher_no=%s AND IFNULL(is_cancelled,0)=0
		""",
		je,
		as_dict=True,
	):
		m[r.account].add((r.party_type or None, r.party or None))
	return {k: sorted(v) for k, v in m.items()}


class TestReturnFromBankBackendE2E(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")
		cls.company = _company()
		cls.customer = frappe.db.get_value("Customer", {"disabled": 0}, "name", order_by="modified desc")
		cls.bank_account = frappe.db.get_value(
			"Bank Account",
			{"company": cls.company, "disabled": 0, "is_company_account": 1},
			"name",
			order_by="modified desc",
		)
		cls.drawer_bank = frappe.db.get_value("Bank", {}, "name", order_by="modified desc")
		cls.settings = _get_pdc_settings_for_company(cls.company)
		if not all([cls.company, cls.customer, cls.bank_account, cls.settings, cls.drawer_bank]):
			raise unittest.SkipTest("Missing company/customer/bank/PDC Settings for Return from Bank E2E")

	def _new_recv(self, amount: float = 125.0, *, prefix: str = "RFB"):
		stamp = int(time.time() * 1000) % 10_000_000
		acc = get_default_party_accounts("Customer", self.customer, self.company, "Receivable") or {}
		doc = frappe.new_doc("Post Dated Cheque")
		doc.cheque_direction = "Receivable"
		doc.company = self.company
		doc.party_type = "Customer"
		doc.party = self.customer
		doc.cheque_no = f"{prefix}-{stamp}-{amount}"
		doc.cheque_due_date = getdate(today()) + timedelta(days=30)
		doc.cheque_amount = amount
		doc.received_date = today()
		doc.drawer_bank_name = self.drawer_bank
		doc.bank_account = self.bank_account
		doc.account_paid_to = acc.get("account_paid_to") or self.settings.default_cheques_in_hand_account
		doc.account_paid_from = acc.get("account_paid_from")
		doc.workflow_state = WORKFLOW_DRAFT
		doc.allocation_mode = "direct_settlement"
		doc.sayad_code = f"SAYAD-{doc.cheque_no}"[:32]
		doc.sayad_registered = 1
		doc.insert(ignore_permissions=True)
		frappe.db.commit()
		return doc

	def _transition(self, doc, frm: str, to: str, **dates):
		doc.reload()
		for k, v in dates.items():
			setattr(doc, k, v)
		doc.workflow_state = to
		doc.flags.ignore_validate_update_after_submit = True
		doc.save(ignore_permissions=True)
		frappe.db.commit()
		doc.reload()
		je = post_pdc_transition_journal_entry(doc, frm, to, posting_date=dates.get(
			"returned_from_bank_date"
		) or dates.get("sent_to_bank_date") or dates.get("cleared_date") or dates.get("bounced_date") or today())
		frappe.db.commit()
		doc.reload()
		return je

	def test_normal_return_from_bank(self):
		doc = self._new_recv(201)
		# Chronology: received < sent < returned (Return later than Send must succeed).
		received = getdate(today()) - timedelta(days=40)
		sent_date = getdate(today()) - timedelta(days=30)
		frappe.db.set_value("Post Dated Cheque", doc.name, "received_date", received, update_modified=False)
		frappe.db.commit()
		doc.reload()
		self._transition(doc, WORKFLOW_DRAFT, WORKFLOW_REGISTERED)
		je_send = self._transition(doc, WORKFLOW_REGISTERED, WORKFLOW_SENT_TO_BANK, sent_to_bank_date=sent_date)
		self.assertTrue(je_send)
		doc.reload()
		prev_sent = doc.sent_to_bank_date
		prev_bank = doc.bank_account
		ret_date = today()
		self.assertGreater(getdate(ret_date), getdate(sent_date))
		je_ret = self._transition(
			doc, WORKFLOW_SENT_TO_BANK, WORKFLOW_REGISTERED, returned_from_bank_date=ret_date
		)
		self.assertTrue(je_ret)
		doc.reload()
		self.assertEqual(normalize_workflow_state_value(doc.workflow_state), WORKFLOW_REGISTERED)
		self.assertEqual(doc.cheque_status, map_workflow_state_to_cheque_status("Receivable", WORKFLOW_REGISTERED))
		self.assertEqual(int(doc.is_at_bank or 0), 0)
		self.assertEqual(getdate(doc.sent_to_bank_date), getdate(prev_sent))
		self.assertEqual(doc.bank_account, prev_bank)
		self.assertEqual(getdate(doc.returned_from_bank_date), getdate(ret_date))

		send_rows = frappe.get_all(
			"Journal Entry Account",
			filters={"parent": je_send},
			fields=["account", "debit_in_account_currency", "credit_in_account_currency", "party", "party_type"],
		)
		ret_rows = frappe.get_all(
			"Journal Entry Account",
			filters={"parent": je_ret},
			fields=["account", "debit_in_account_currency", "credit_in_account_currency", "party", "party_type"],
		)
		self.assertEqual(len(send_rows), 2)
		self.assertEqual(len(ret_rows), 2)
		# Reverse of send accounts
		send_dr = next(r for r in send_rows if flt(r.debit_in_account_currency))
		send_cr = next(r for r in send_rows if flt(r.credit_in_account_currency))
		ret_dr = next(r for r in ret_rows if flt(r.debit_in_account_currency))
		ret_cr = next(r for r in ret_rows if flt(r.credit_in_account_currency))
		self.assertEqual(ret_dr.account, send_cr.account)
		self.assertEqual(ret_cr.account, send_dr.account)
		for r in ret_rows:
			self.assertEqual(r.party, self.customer)
			self.assertEqual(r.party_type, "Customer")
		self.assertEqual(_party_map_je(je_ret), _party_map_gl(je_ret))
		purposes = frappe.get_all(
			"PDC Journal Reference",
			filters={"parent": doc.name, "journal_entry": je_ret},
			pluck="purpose",
		)
		self.assertEqual(purposes, ["Return from Bank"])

	def test_opening_balance_return_without_send_je(self):
		doc = self._new_recv(202, prefix="RFB-OB")
		self._transition(doc, WORKFLOW_DRAFT, WORKFLOW_REGISTERED)
		# Opening-style: land on Sent to Bank without a Send JE (no Under Collection ref).
		frappe.db.set_value(
			"Post Dated Cheque",
			doc.name,
			{
				"workflow_state": WORKFLOW_SENT_TO_BANK,
				"cheque_status": map_workflow_state_to_cheque_status("Receivable", WORKFLOW_SENT_TO_BANK),
				"sent_to_bank_date": today(),
				"is_at_bank": 1,
			},
			update_modified=False,
		)
		frappe.db.commit()
		doc.reload()
		self.assertFalse(
			frappe.db.exists(
				"PDC Journal Reference",
				{"parent": doc.name, "purpose": "Under Collection"},
			)
		)
		je_ret = self._transition(
			doc, WORKFLOW_SENT_TO_BANK, WORKFLOW_REGISTERED, returned_from_bank_date=today()
		)
		self.assertTrue(je_ret)
		doc.reload()
		self.assertEqual(normalize_workflow_state_value(doc.workflow_state), WORKFLOW_REGISTERED)
		self.assertEqual(_party_map_je(je_ret), _party_map_gl(je_ret))

	def test_multiple_cycles_create_distinct_jes(self):
		doc = self._new_recv(203, prefix="RFB-CY")
		self._transition(doc, WORKFLOW_DRAFT, WORKFLOW_REGISTERED)
		je_s1 = self._transition(doc, WORKFLOW_REGISTERED, WORKFLOW_SENT_TO_BANK, sent_to_bank_date=today())
		je_r1 = self._transition(
			doc, WORKFLOW_SENT_TO_BANK, WORKFLOW_REGISTERED, returned_from_bank_date=today()
		)
		# Re-send with same or later date (>= returned_from_bank_date)
		je_s2 = self._transition(doc, WORKFLOW_REGISTERED, WORKFLOW_SENT_TO_BANK, sent_to_bank_date=today())
		je_r2 = self._transition(
			doc, WORKFLOW_SENT_TO_BANK, WORKFLOW_REGISTERED, returned_from_bank_date=today()
		)
		self.assertEqual(len({je_s1, je_s2}), 2)
		self.assertEqual(len({je_r1, je_r2}), 2)
		send_refs = frappe.get_all(
			"PDC Journal Reference",
			filters={"parent": doc.name, "purpose": "Under Collection"},
			pluck="journal_entry",
		)
		ret_refs = frappe.get_all(
			"PDC Journal Reference",
			filters={"parent": doc.name, "purpose": "Return from Bank"},
			pluck="journal_entry",
		)
		self.assertEqual(len(send_refs), 2)
		self.assertEqual(len(ret_refs), 2)

	def test_idempotent_retry_reuses_open_return_je(self):
		doc = self._new_recv(204, prefix="RFB-ID")
		self._transition(doc, WORKFLOW_DRAFT, WORKFLOW_REGISTERED)
		self._transition(doc, WORKFLOW_REGISTERED, WORKFLOW_SENT_TO_BANK, sent_to_bank_date=today())
		je1 = self._transition(
			doc, WORKFLOW_SENT_TO_BANK, WORKFLOW_REGISTERED, returned_from_bank_date=today()
		)
		# Retry same edge while still "open" (no later Send) — should reuse
		doc.reload()
		je2 = post_pdc_transition_journal_entry(
			doc, WORKFLOW_SENT_TO_BANK, WORKFLOW_REGISTERED, posting_date=today()
		)
		frappe.db.commit()
		self.assertEqual(je1, je2)

	def test_invalid_states_blocked(self):
		self.assertFalse(is_workflow_transition_allowed("Receivable", WORKFLOW_CLEARED, WORKFLOW_REGISTERED))
		self.assertFalse(is_workflow_transition_allowed("Receivable", WORKFLOW_BOUNCED, WORKFLOW_REGISTERED))
		err = get_pdc_workflow_transition_validation_error(
			WORKFLOW_CLEARED, WORKFLOW_REGISTERED, "Receivable"
		)
		self.assertTrue(err)


if __name__ == "__main__":
	unittest.main()
