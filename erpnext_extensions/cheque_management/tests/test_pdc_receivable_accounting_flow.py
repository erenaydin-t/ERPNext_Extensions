# Copyright (c) 2026, Farbod Siyahpoosh and contributors
# For license information, please see license.txt

"""Multi-transition **Receivable** accounting shape tests (no database).

* Register / send-to-bank / clear at bank are **Journal Entry** (clear: Dr bank, Cr intermediary; no party).
* No Payment Entry exists in this PDC lifecycle.
"""

from __future__ import annotations

import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

import erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque as pdc_mod

from erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque import (
	build_pdc_journal_entry_data,
)
from erpnext_extensions.cheque_management.pdc_journal_entry_service import build_pdc_transition_key
from erpnext_extensions.cheque_management.pdc_workflow_state_machine import (
	CHEQUE_DIRECTION_RECEIVABLE,
	WORKFLOW_BOUNCED,
	WORKFLOW_CLEARED,
	WORKFLOW_DRAFT,
	WORKFLOW_REGISTERED,
	WORKFLOW_RETURNED,
	WORKFLOW_SENT_TO_BANK,
)

POSTING = date(2026, 4, 3)

_SETTINGS: dict = {
	"default_cheques_in_hand_account": "ACC-CIH",
	"default_cheques_in_clearing_account": "ACC-CLR",
	"default_payable_cheque_account": "ACC-POOL",
	"default_protested_account": "ACC-PROT",
	"default_endorsement_account": None,
}


def _party_touch_count(je: dict) -> int:
	n = 0
	for row in je.get("accounts") or []:
		if row.get("party_type") or row.get("party"):
			n += 1
	return n


def _doc():
	return SimpleNamespace(
		company="_TC",
		cheque_direction=CHEQUE_DIRECTION_RECEIVABLE,
		party_type="Customer",
		party="C-1",
		cheque_amount=2500.0,
		cheque_no="PDC-FLOW-1",
		account_paid_to="ACC-CIH",
		account_paid_from="ACC-AR",
		bank_account="BA-COMP",
		holder_party_type=None,
		holder_party=None,
	)


class TestPDCReceivableAccountingFlow(unittest.TestCase):
	def test_draft_registered_sent_cleared_all_journal_no_pe(self) -> None:
		doc = _doc()
		with (
			patch.object(pdc_mod, "_get_pdc_settings_for_company", return_value=dict(_SETTINGS)),
			patch.object(pdc_mod, "_get_party_account_or_company_default", return_value="ACC-AR-FB"),
			patch.object(pdc_mod, "_pdc_bank_gl_account", return_value="ACC-BANK"),
			patch.object(pdc_mod, "frappe") as mf,
		):
			mf._ = lambda s: s
			j1 = build_pdc_journal_entry_data(doc, WORKFLOW_DRAFT, WORKFLOW_REGISTERED, POSTING)
			j2 = build_pdc_journal_entry_data(doc, WORKFLOW_REGISTERED, WORKFLOW_SENT_TO_BANK, POSTING)
			j3 = build_pdc_journal_entry_data(doc, WORKFLOW_SENT_TO_BANK, WORKFLOW_CLEARED, POSTING)
		assert j1 and j2 and j3
		self.assertEqual(_party_touch_count(j1), 1)
		self.assertEqual(_party_touch_count(j2), 0)
		self.assertEqual(_party_touch_count(j3), 0)
		self.assertEqual(j3["accounts"][0]["account"], "ACC-BANK")
		self.assertEqual(j3["accounts"][1]["account"], "ACC-CLR")

	def test_draft_registered_direct_clear_is_je_not_pe(self) -> None:
		doc = _doc()
		with (
			patch.object(pdc_mod, "_get_pdc_settings_for_company", return_value=dict(_SETTINGS)),
			patch.object(pdc_mod, "_get_party_account_or_company_default", return_value="ACC-AR-FB"),
			patch.object(pdc_mod, "_pdc_bank_gl_account", return_value="ACC-BANK"),
			patch.object(pdc_mod, "frappe") as mf,
		):
			mf._ = lambda s: s
			j1 = build_pdc_journal_entry_data(doc, WORKFLOW_DRAFT, WORKFLOW_REGISTERED, POSTING)
			j_clear = build_pdc_journal_entry_data(doc, WORKFLOW_REGISTERED, WORKFLOW_CLEARED, POSTING)
		assert j1 and j_clear
		self.assertEqual(j_clear["accounts"][0]["account"], "ACC-BANK")
		self.assertEqual(j_clear["accounts"][1]["account"], "ACC-CIH")

	def test_registered_sent_bounced_no_party(self) -> None:
		doc = _doc()
		with (
			patch.object(pdc_mod, "_get_pdc_settings_for_company", return_value=dict(_SETTINGS)),
			patch.object(pdc_mod, "_get_party_account_or_company_default", return_value="ACC-AR-FB"),
			patch.object(pdc_mod, "_pdc_bank_gl_account", return_value="ACC-BANK"),
			patch.object(pdc_mod, "frappe") as mf,
		):
			mf._ = lambda s: s
			j_b = build_pdc_journal_entry_data(doc, WORKFLOW_SENT_TO_BANK, WORKFLOW_BOUNCED, POSTING)
		assert j_b
		self.assertEqual(j_b["accounts"][1]["account"], "ACC-CLR")
		dr = j_b["accounts"][0]
		self.assertNotIn("party_type", dr)

	def test_registered_returned_reverses_party_once(self) -> None:
		doc = _doc()
		with (
			patch.object(pdc_mod, "_get_pdc_settings_for_company", return_value=dict(_SETTINGS)),
			patch.object(pdc_mod, "_get_party_account_or_company_default", return_value="ACC-AR-FB"),
			patch.object(pdc_mod, "_pdc_bank_gl_account", return_value="ACC-BANK"),
			patch.object(pdc_mod, "frappe") as mf,
		):
			mf._ = lambda s: s
			j_reg = build_pdc_journal_entry_data(doc, WORKFLOW_DRAFT, WORKFLOW_REGISTERED, POSTING)
			j_ret = build_pdc_journal_entry_data(doc, WORKFLOW_REGISTERED, WORKFLOW_RETURNED, POSTING)
		assert j_reg and j_ret
		self.assertEqual(_party_touch_count(j_reg), 1)
		self.assertEqual(_party_touch_count(j_ret), 1)

	def test_transition_keys_unique_per_edge(self) -> None:
		k1 = build_pdc_transition_key(CHEQUE_DIRECTION_RECEIVABLE, WORKFLOW_DRAFT, WORKFLOW_REGISTERED)
		k2 = build_pdc_transition_key(
			CHEQUE_DIRECTION_RECEIVABLE, WORKFLOW_REGISTERED, WORKFLOW_SENT_TO_BANK
		)
		k3 = build_pdc_transition_key(
			CHEQUE_DIRECTION_RECEIVABLE, WORKFLOW_SENT_TO_BANK, WORKFLOW_CLEARED
		)
		self.assertEqual(len({k1, k2, k3}), 3)


if __name__ == "__main__":
	unittest.main()
