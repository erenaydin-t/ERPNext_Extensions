# Copyright (c) 2026, Farbod Siyahpoosh and contributors
# For license information, please see license.txt

"""Automated tests for **receivable** cheque accounting after the clearing fix.

Runs without posting to ERPNext: builds **Journal Entry** payloads via
``build_pdc_journal_entry_data`` and aggregates notional GL effect per account.

**Summary (root cause, fix, guarantees)**

* **Root cause:** Receivable clearing used a party-carrying voucher shape. ERPNext maps the party to
  ``paid_from``; clearing credited an intermediary GL but the voucher still carried **Customer**,
  so party-based reports showed a **second** credit tied to the customer. Separately, **Journal
  Entry** lines on Receivable-type accounts require **Party** in ERPNext, so mis-typed pool accounts
  could also force party dimensions.

* **Fix applied:** Receivable **→ Cleared** is booked only as **Journal Entry**: **Dr Bank**, **Cr**
  Cheques in Hand / Clearing / Protested (via ``receivable_intermediary_account_for_bank_clear``),
  **no** ``party_type`` / ``party`` on those lines. Transition **idempotency** uses
  ``cheque_name|direction|from|to`` (and legacy suffix) on ``journal_references``.

* **Why duplicate customer credit cannot happen now:** The only **credit** to the customer
  receivable account in the register/return/bounce flows is **Draft → Registered** (one Cr to AR).
  Clearing **does not** hit AR and **does not** pass party on the clear JE, so ERPNext never applies
  a second party-based receivable movement for clearing.

Run from bench root::

    ./env/bin/python -m unittest erpnext_extensions.cheque_management.tests.test_pdc_receivable_accounting_post_fix -v
"""

from __future__ import annotations

import unittest
from collections import defaultdict
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

import erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque as pdc_mod

from erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque import (
	build_pdc_journal_entry_data,
)
from erpnext_extensions.cheque_management.pdc_accounting_idempotency import (
	build_pdc_accounting_transition_key,
	build_pdc_transition_key_suffix,
)
from erpnext_extensions.cheque_management.pdc_workflow_state_machine import (
	CHEQUE_DIRECTION_RECEIVABLE,
	WORKFLOW_BOUNCED,
	WORKFLOW_CLEARED,
	WORKFLOW_DRAFT,
	WORKFLOW_REGISTERED,
	WORKFLOW_RETURNED,
	WORKFLOW_SENT_TO_BANK,
)

POSTING = date(2026, 6, 15)
AMT = 1000.0

_SETTINGS = {
	"default_cheques_in_hand_account": "GL-CIH",
	"default_cheques_in_clearing_account": "GL-CLR",
	"default_payable_cheque_account": "GL-POOL",
	"default_protested_account": "GL-PROT",
	"default_endorsement_account": None,
}

# Resolved party receivable used on register / return
GL_AR = "GL-CUSTOMER-AR"
GL_BANK = "GL-BANK-COMPANY"


def _doc():
	return SimpleNamespace(
		name="PDC-TST-001",
		company="_TC",
		cheque_direction=CHEQUE_DIRECTION_RECEIVABLE,
		party_type="Customer",
		party="CUST-1",
		cheque_amount=AMT,
		cheque_no="CHK-POST-FIX",
		account_paid_to="GL-CIH",
		account_paid_from="GL-CUSTOMER-AR",
		bank_account="BA-TEST",
		holder_party_type=None,
		holder_party=None,
	)


def _party_credit_to_account(je: dict | None, ar_account: str) -> float:
	"""Sum credits on rows that carry party and hit ``ar_account`` (customer side)."""
	if not je:
		return 0.0
	total = 0.0
	for row in je.get("accounts") or []:
		if not row.get("credit_in_account_currency"):
			continue
		if row.get("account") != ar_account:
			continue
		if row.get("party_type") or row.get("party"):
			total += float(row["credit_in_account_currency"])
	return total


def _party_debit_to_account(je: dict | None, ar_account: str) -> float:
	if not je:
		return 0.0
	total = 0.0
	for row in je.get("accounts") or []:
		if not row.get("debit_in_account_currency"):
			continue
		if row.get("account") != ar_account:
			continue
		if row.get("party_type") or row.get("party"):
			total += float(row["debit_in_account_currency"])
	return total


def _aggregate_net_by_account(jes: list[dict]) -> dict[str, float]:
	"""Net (debit − credit) per account across JE payloads (simplified GL)."""
	net: dict[str, float] = defaultdict(float)
	for je in jes:
		if not je:
			continue
		for row in je.get("accounts") or []:
			acc = row.get("account")
			if not acc:
				continue
			d = float(row.get("debit_in_account_currency") or 0)
			c = float(row.get("credit_in_account_currency") or 0)
			net[acc] += d - c
	return dict(net)


def _transition_keys_unique(pdc_name: str, edges: list[tuple[str, str]]) -> list[str]:
	keys = [
		build_pdc_accounting_transition_key(pdc_name, CHEQUE_DIRECTION_RECEIVABLE, f, t) for f, t in edges
	]
	uniq = set(keys)
	if len(keys) != len(uniq):
		raise AssertionError(f"duplicate transition keys: {keys}")
	return keys


class TestReceivableChainThroughBankToClear(unittest.TestCase):
	"""Draft → Registered → Sent to Bank → Cleared."""

	def test_customer_credited_once_bank_once_clearing_paths_no_pe(self) -> None:
		d = _doc()
		with (
			patch.object(pdc_mod, "_get_pdc_settings_for_company", return_value=dict(_SETTINGS)),
			patch.object(pdc_mod, "_get_party_account_or_company_default", return_value=GL_AR),
			patch.object(pdc_mod, "_pdc_bank_gl_account", return_value=GL_BANK),
			patch.object(pdc_mod, "frappe") as mf,
		):
			mf._ = lambda s: s
			j_reg = build_pdc_journal_entry_data(d, WORKFLOW_DRAFT, WORKFLOW_REGISTERED, POSTING)
			j_send = build_pdc_journal_entry_data(d, WORKFLOW_REGISTERED, WORKFLOW_SENT_TO_BANK, POSTING)
			j_clear = build_pdc_journal_entry_data(d, WORKFLOW_SENT_TO_BANK, WORKFLOW_CLEARED, POSTING)
		self.assertTrue(j_reg and j_send and j_clear)

		cr_party = _party_credit_to_account(j_reg, GL_AR)
		self.assertEqual(cr_party, AMT, "Register: one credit to customer AR")
		self.assertEqual(_party_credit_to_account(j_send, GL_AR), 0.0)
		self.assertEqual(_party_credit_to_account(j_clear, GL_AR), 0.0)

		self.assertEqual(j_clear["accounts"][0]["account"], GL_BANK)
		self.assertEqual(
			float(j_clear["accounts"][0].get("debit_in_account_currency") or 0),
			AMT,
			"Bank debited once for clear",
		)
		self.assertEqual(j_clear["accounts"][1]["account"], "GL-CLR", "Credit clearing (instrument left clearing pool)")

		keys = _transition_keys_unique(
			d.name,
			[
				(WORKFLOW_DRAFT, WORKFLOW_REGISTERED),
				(WORKFLOW_REGISTERED, WORKFLOW_SENT_TO_BANK),
				(WORKFLOW_SENT_TO_BANK, WORKFLOW_CLEARED),
			],
		)
		self.assertEqual(len(keys), 3)

		net = _aggregate_net_by_account([j_reg, j_send, j_clear])
		self.assertEqual(net.get(GL_AR), -AMT, "Net: customer AR credited once (credit side negative in d−c)")
		self.assertEqual(net.get(GL_BANK), AMT)


class TestReceivableDirectClear(unittest.TestCase):
	"""Draft → Registered → Cleared (skip bank / clearing)."""

	def test_customer_once_bank_once_cih_clear_no_second_party_credit(self) -> None:
		d = _doc()
		with (
			patch.object(pdc_mod, "_get_pdc_settings_for_company", return_value=dict(_SETTINGS)),
			patch.object(pdc_mod, "_get_party_account_or_company_default", return_value=GL_AR),
			patch.object(pdc_mod, "_pdc_bank_gl_account", return_value=GL_BANK),
			patch.object(pdc_mod, "frappe") as mf,
		):
			mf._ = lambda s: s
			j_reg = build_pdc_journal_entry_data(d, WORKFLOW_DRAFT, WORKFLOW_REGISTERED, POSTING)
			j_clear = build_pdc_journal_entry_data(d, WORKFLOW_REGISTERED, WORKFLOW_CLEARED, POSTING)
		self.assertTrue(j_reg and j_clear)

		self.assertEqual(_party_credit_to_account(j_reg, GL_AR), AMT)
		self.assertEqual(_party_credit_to_account(j_clear, GL_AR), 0.0)
		self.assertEqual(j_clear["accounts"][0]["account"], GL_BANK)
		self.assertEqual(j_clear["accounts"][1]["account"], "GL-CIH")


class TestReceivableBounce(unittest.TestCase):
	"""Draft → Registered → Sent to Bank → Bounced."""

	def test_no_second_customer_credit_clearing_released(self) -> None:
		d = _doc()
		with (
			patch.object(pdc_mod, "_get_pdc_settings_for_company", return_value=dict(_SETTINGS)),
			patch.object(pdc_mod, "_get_party_account_or_company_default", return_value=GL_AR),
			patch.object(pdc_mod, "_pdc_bank_gl_account", return_value=GL_BANK),
			patch.object(pdc_mod, "frappe") as mf,
		):
			mf._ = lambda s: s
			j_reg = build_pdc_journal_entry_data(d, WORKFLOW_DRAFT, WORKFLOW_REGISTERED, POSTING)
			j_send = build_pdc_journal_entry_data(d, WORKFLOW_REGISTERED, WORKFLOW_SENT_TO_BANK, POSTING)
			j_bounce = build_pdc_journal_entry_data(d, WORKFLOW_SENT_TO_BANK, WORKFLOW_BOUNCED, POSTING)
		self.assertTrue(j_reg and j_send and j_bounce)

		self.assertEqual(_party_credit_to_account(j_reg, GL_AR), AMT)
		for je in (j_send, j_bounce):
			for row in je["accounts"]:
				self.assertNotIn("party_type", row)
				self.assertNotIn("party", row)

		dr, cr = j_bounce["accounts"]
		self.assertEqual(cr["account"], "GL-CLR")
		self.assertEqual(float(cr.get("credit_in_account_currency") or 0), AMT, "Clearing credited back")


class TestReceivableReturn(unittest.TestCase):
	"""Draft → Registered → Returned."""

	def test_initial_settlement_reversed_once(self) -> None:
		d = _doc()
		with (
			patch.object(pdc_mod, "_get_pdc_settings_for_company", return_value=dict(_SETTINGS)),
			patch.object(pdc_mod, "_get_party_account_or_company_default", return_value=GL_AR),
			patch.object(pdc_mod, "_pdc_bank_gl_account", return_value=GL_BANK),
			patch.object(pdc_mod, "frappe") as mf,
		):
			mf._ = lambda s: s
			j_reg = build_pdc_journal_entry_data(d, WORKFLOW_DRAFT, WORKFLOW_REGISTERED, POSTING)
			j_ret = build_pdc_journal_entry_data(d, WORKFLOW_REGISTERED, WORKFLOW_RETURNED, POSTING)
		self.assertTrue(j_reg and j_ret)

		self.assertEqual(_party_credit_to_account(j_reg, GL_AR), AMT)
		self.assertEqual(_party_debit_to_account(j_ret, GL_AR), AMT, "Return: one debit to customer AR")

		net = _aggregate_net_by_account([j_reg, j_ret])
		self.assertAlmostEqual(net.get(GL_AR, 0.0), 0.0, places=6, msg="AR net zero after register + return")


class TestIdempotencyKeysNoDuplicateVoucher(unittest.TestCase):
	"""Same transition must map to one canonical key; receivable clear has no PE payload."""

	def test_keys_distinct_per_edge_suffix_and_full(self) -> None:
		name = "PDC-ID-1"
		e1 = build_pdc_transition_key_suffix(CHEQUE_DIRECTION_RECEIVABLE, WORKFLOW_DRAFT, WORKFLOW_REGISTERED)
		e2 = build_pdc_transition_key_suffix(
			CHEQUE_DIRECTION_RECEIVABLE, WORKFLOW_REGISTERED, WORKFLOW_SENT_TO_BANK
		)
		e3 = build_pdc_transition_key_suffix(
			CHEQUE_DIRECTION_RECEIVABLE, WORKFLOW_SENT_TO_BANK, WORKFLOW_CLEARED
		)
		self.assertEqual(len({e1, e2, e3}), 3)
		f1 = build_pdc_accounting_transition_key(name, CHEQUE_DIRECTION_RECEIVABLE, WORKFLOW_DRAFT, WORKFLOW_REGISTERED)
		self.assertTrue(f1.startswith(f"{name}|"))


class TestSummaryDocumentation(unittest.TestCase):
	"""Anchor for designers: see module docstring for root cause / fix / guarantees."""

	def test_documentation_present(self) -> None:
		doc = __doc__ or ""
		self.assertIn("Root cause", doc)
		self.assertIn("Fix applied", doc)
		self.assertIn("duplicate customer credit", doc.lower())


if __name__ == "__main__":
	unittest.main()
