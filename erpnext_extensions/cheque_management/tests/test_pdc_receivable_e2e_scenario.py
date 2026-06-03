# Copyright (c) 2026, Farbod Siyahpoosh and contributors
# For license information, please see license.txt

"""End-to-end **Receivable PDC** scenario tests (payload + status; no live GL posting).

Exercises the full intended lifecycle in **six** accounting-relevant transitions:

1. Draft → Registered
2. Registered → Sent to Bank
3. Sent to Bank → Cleared
4. Registered → Cleared
5. Registered → Returned
6. Registered → Endorsed

Verifies:

* ``cheque_status`` from ``map_workflow_state_to_cheque_status``
* ``build_pdc_journal_entry_data`` account lines per edge
* Party on both JE lines except **bank** on clear JEs
* Company **Bank** GL (``ACC-BANK``) appears **only** on **→ Cleared** payloads

Run from bench root::

    ./env/bin/python -m unittest erpnext_extensions.cheque_management.tests.test_pdc_receivable_e2e_scenario -v
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
from erpnext_extensions.cheque_management.pdc_workflow_to_cheque_status import (
	CHEQUE_STATUS_CLEARED,
	CHEQUE_STATUS_ENDORSED,
	CHEQUE_STATUS_IN_CLEARING,
	CHEQUE_STATUS_IN_HAND,
	CHEQUE_STATUS_RETURNED_TO_CUSTOMER,
	map_workflow_state_to_cheque_status,
)
from erpnext_extensions.cheque_management.pdc_workflow_state_machine import (
	CHEQUE_DIRECTION_RECEIVABLE,
	WORKFLOW_DRAFT,
	WORKFLOW_ENDORSED,
	WORKFLOW_REGISTERED,
	WORKFLOW_RETURNED,
	WORKFLOW_SENT_TO_BANK,
	WORKFLOW_CLEARED,
)

POSTING = date(2026, 8, 1)

_BANK_GL = "ACC-BANK"

_SETTINGS: dict = {
	"default_cheques_in_hand_account": "ACC-CIH",
	"default_cheques_in_clearing_account": "ACC-CLR",
	"default_payable_cheque_account": "ACC-POOL",
	"default_protested_account": "ACC-PROT",
	"default_endorsement_account": "ACC-ENDORSE-GL",
}


def _base_doc() -> SimpleNamespace:
	return SimpleNamespace(
		company="_TC",
		cheque_direction=CHEQUE_DIRECTION_RECEIVABLE,
		party_type="Customer",
		party="CUST-1",
		cheque_amount=1000.0,
		cheque_no="E2E-R-001",
		account_paid_to="ACC-CIH",
		account_paid_from="ACC-AR-DOC",
		bank_account="BA-COMP",
		holder_party_type=None,
		holder_party=None,
	)


def _party_line_count(je: dict | None) -> int:
	if not je:
		return 0
	n = 0
	for row in je.get("accounts") or []:
		if row.get("party_type") or row.get("party"):
			n += 1
	return n


def _bank_gl_line_count(je: dict | None, bank_gl: str = _BANK_GL) -> int:
	if not je:
		return 0
	return sum(1 for r in je.get("accounts") or [] if r.get("account") == bank_gl)


class TestReceivablePDCEndToEndScenario(unittest.TestCase):
	"""Receivable chain: status ladder + JE shapes + bank only on clear."""

	def test_cheque_status_for_each_target_state(self) -> None:
		cases = [
			(WORKFLOW_REGISTERED, CHEQUE_STATUS_IN_HAND),
			(WORKFLOW_SENT_TO_BANK, CHEQUE_STATUS_IN_CLEARING),
			(WORKFLOW_CLEARED, CHEQUE_STATUS_CLEARED),
			(WORKFLOW_RETURNED, CHEQUE_STATUS_RETURNED_TO_CUSTOMER),
			(WORKFLOW_ENDORSED, CHEQUE_STATUS_ENDORSED),
		]
		for ws, expected in cases:
			with self.subTest(workflow_state=ws):
				self.assertEqual(
					map_workflow_state_to_cheque_status(CHEQUE_DIRECTION_RECEIVABLE, ws),
					expected,
				)

	def test_draft_to_registered_dr_cih_cr_party_ar(self) -> None:
		doc = _base_doc()
		with (
			patch.object(pdc_mod, "_get_pdc_settings_for_company", return_value=dict(_SETTINGS)),
			patch.object(pdc_mod, "_get_party_account_or_company_default", return_value="ACC-AR-RESOLVED"),
			patch.object(pdc_mod, "_pdc_bank_gl_account", return_value=_BANK_GL),
			patch.object(pdc_mod, "frappe") as mf,
		):
			mf._ = lambda s: s
			je = build_pdc_journal_entry_data(doc, WORKFLOW_DRAFT, WORKFLOW_REGISTERED, POSTING)
		self.assertIsNotNone(je)
		self.assertEqual(_party_line_count(je), 2)
		self.assertEqual(_bank_gl_line_count(je), 0)
		dr, cr = je["accounts"]
		self.assertEqual(dr["account"], "ACC-CIH")
		self.assertEqual(cr["account"], "ACC-AR-DOC")
		for row in (dr, cr):
			self.assertEqual(row.get("party_type"), "Customer")
			self.assertEqual(row.get("party"), "CUST-1")

	def test_registered_to_sent_to_bank_dr_clearing_cr_cih_no_party(self) -> None:
		doc = _base_doc()
		with (
			patch.object(pdc_mod, "_get_pdc_settings_for_company", return_value=dict(_SETTINGS)),
			patch.object(pdc_mod, "_get_party_account_or_company_default", return_value="ACC-AR-RESOLVED"),
			patch.object(pdc_mod, "_pdc_bank_gl_account", return_value=_BANK_GL),
			patch.object(pdc_mod, "frappe") as mf,
		):
			mf._ = lambda s: s
			je = build_pdc_journal_entry_data(doc, WORKFLOW_REGISTERED, WORKFLOW_SENT_TO_BANK, POSTING)
		self.assertIsNotNone(je)
		self.assertEqual(_party_line_count(je), 2)
		self.assertEqual(_bank_gl_line_count(je), 0)
		dr, cr = je["accounts"]
		self.assertEqual(dr["account"], "ACC-CLR")
		self.assertEqual(cr["account"], "ACC-CIH")
		for row in (dr, cr):
			self.assertEqual(row.get("party"), "CUST-1")

	def test_sent_to_bank_to_cleared_dr_bank_cr_clearing_no_party(self) -> None:
		doc = _base_doc()
		with (
			patch.object(pdc_mod, "_get_pdc_settings_for_company", return_value=dict(_SETTINGS)),
			patch.object(pdc_mod, "_get_party_account_or_company_default", return_value="ACC-AR-RESOLVED"),
			patch.object(pdc_mod, "_pdc_bank_gl_account", return_value=_BANK_GL),
			patch.object(pdc_mod, "frappe") as mf,
		):
			mf._ = lambda s: s
			je = build_pdc_journal_entry_data(doc, WORKFLOW_SENT_TO_BANK, WORKFLOW_CLEARED, POSTING)
		self.assertIsNotNone(je)
		self.assertEqual(je["voucher_type"], "Bank Entry")
		self.assertEqual(_party_line_count(je), 1)
		self.assertEqual(_bank_gl_line_count(je), 1)
		dr, cr = je["accounts"]
		self.assertEqual(dr["account"], _BANK_GL)
		self.assertEqual(cr["account"], "ACC-CLR")
		self.assertNotIn("party_type", dr)
		self.assertEqual(cr.get("party"), "CUST-1")

	def test_registered_to_cleared_dr_bank_cr_cih_no_party(self) -> None:
		doc = _base_doc()
		with (
			patch.object(pdc_mod, "_get_pdc_settings_for_company", return_value=dict(_SETTINGS)),
			patch.object(pdc_mod, "_get_party_account_or_company_default", return_value="ACC-AR-RESOLVED"),
			patch.object(pdc_mod, "_pdc_bank_gl_account", return_value=_BANK_GL),
			patch.object(pdc_mod, "frappe") as mf,
		):
			mf._ = lambda s: s
			je = build_pdc_journal_entry_data(doc, WORKFLOW_REGISTERED, WORKFLOW_CLEARED, POSTING)
		self.assertIsNotNone(je)
		self.assertEqual(je["voucher_type"], "Bank Entry")
		self.assertEqual(_party_line_count(je), 1)
		self.assertEqual(_bank_gl_line_count(je), 1)
		dr, cr = je["accounts"]
		self.assertEqual(dr["account"], _BANK_GL)
		self.assertEqual(cr["account"], "ACC-CIH")
		self.assertNotIn("party_type", dr)
		self.assertEqual(cr.get("party"), "CUST-1")

	def test_registered_to_returned_dr_ar_cr_cih_one_party(self) -> None:
		doc = _base_doc()
		with (
			patch.object(pdc_mod, "_get_pdc_settings_for_company", return_value=dict(_SETTINGS)),
			patch.object(pdc_mod, "_get_party_account_or_company_default", return_value="ACC-AR-RESOLVED"),
			patch.object(pdc_mod, "_pdc_bank_gl_account", return_value=_BANK_GL),
			patch.object(pdc_mod, "frappe") as mf,
		):
			mf._ = lambda s: s
			je = build_pdc_journal_entry_data(doc, WORKFLOW_REGISTERED, WORKFLOW_RETURNED, POSTING)
		self.assertIsNotNone(je)
		self.assertEqual(_party_line_count(je), 2)
		self.assertEqual(_bank_gl_line_count(je), 0)
		dr, cr = je["accounts"]
		self.assertEqual(dr["account"], "ACC-AR-DOC")
		self.assertEqual(dr.get("party_type"), "Customer")
		self.assertEqual(cr["account"], "ACC-CIH")
		self.assertEqual(cr.get("party"), "CUST-1")

	def test_registered_to_endorsed_dr_settlement_cr_cih_no_drawer_party(self) -> None:
		doc = _base_doc()
		doc.holder_party_type = "Customer"
		doc.holder_party = "CUST-ENDORSEE"
		with (
			patch.object(pdc_mod, "_get_pdc_settings_for_company", return_value=dict(_SETTINGS)),
			patch.object(pdc_mod, "_get_party_account_or_company_default", return_value="ACC-AR-RESOLVED"),
			patch.object(pdc_mod, "_pdc_bank_gl_account", return_value=_BANK_GL),
			patch.object(pdc_mod, "frappe") as mf,
		):
			mf._ = lambda s: s
			je = build_pdc_journal_entry_data(doc, WORKFLOW_REGISTERED, WORKFLOW_ENDORSED, POSTING)
		self.assertIsNotNone(je)
		self.assertEqual(_bank_gl_line_count(je), 0)
		for row in je["accounts"]:
			self.assertNotEqual(row.get("party"), "CUST-1")
		dr, cr = je["accounts"]
		self.assertEqual(dr["account"], "ACC-ENDORSE-GL")
		self.assertEqual(cr["account"], "ACC-CIH")
		self.assertEqual(_party_line_count(je), 0)

	def test_bank_gl_only_on_cleared_not_on_register_send_return_endorse(self) -> None:
		"""Bank company ledger appears only on clear JEs; never on register / send / return / endorse."""
		doc = _base_doc()
		doc.holder_party_type = "Customer"
		doc.holder_party = "CUST-ENDORSEE"
		with (
			patch.object(pdc_mod, "_get_pdc_settings_for_company", return_value=dict(_SETTINGS)),
			patch.object(pdc_mod, "_get_party_account_or_company_default", return_value="ACC-AR-RESOLVED"),
			patch.object(pdc_mod, "_pdc_bank_gl_account", return_value=_BANK_GL),
			patch.object(pdc_mod, "frappe") as mf,
		):
			mf._ = lambda s: s
			j_reg = build_pdc_journal_entry_data(doc, WORKFLOW_DRAFT, WORKFLOW_REGISTERED, POSTING)
			j_stb = build_pdc_journal_entry_data(doc, WORKFLOW_REGISTERED, WORKFLOW_SENT_TO_BANK, POSTING)
			j_clr1 = build_pdc_journal_entry_data(doc, WORKFLOW_SENT_TO_BANK, WORKFLOW_CLEARED, POSTING)
			j_clr2 = build_pdc_journal_entry_data(doc, WORKFLOW_REGISTERED, WORKFLOW_CLEARED, POSTING)
			j_ret = build_pdc_journal_entry_data(doc, WORKFLOW_REGISTERED, WORKFLOW_RETURNED, POSTING)
			j_end = build_pdc_journal_entry_data(doc, WORKFLOW_REGISTERED, WORKFLOW_ENDORSED, POSTING)
		for label, je in (
			("register", j_reg),
			("send_to_bank", j_stb),
			("return", j_ret),
			("endorse", j_end),
		):
			with self.subTest(step=label):
				self.assertEqual(_bank_gl_line_count(je), 0, f"{label} must not hit bank GL")
		for label, je in (("clear_after_stb", j_clr1), ("clear_direct", j_clr2)):
			with self.subTest(step=label):
				self.assertEqual(_bank_gl_line_count(je), 1, f"{label} must Dr/Cr bank once")

	def test_clear_jes_party_on_non_bank_line_only(self) -> None:
		"""Cleared payloads: party on cheque pool/clearing credit; bank debit has no party."""
		doc = _base_doc()
		with (
			patch.object(pdc_mod, "_get_pdc_settings_for_company", return_value=dict(_SETTINGS)),
			patch.object(pdc_mod, "_get_party_account_or_company_default", return_value="ACC-AR-RESOLVED"),
			patch.object(pdc_mod, "_pdc_bank_gl_account", return_value=_BANK_GL),
			patch.object(pdc_mod, "frappe") as mf,
		):
			mf._ = lambda s: s
			j1 = build_pdc_journal_entry_data(doc, WORKFLOW_SENT_TO_BANK, WORKFLOW_CLEARED, POSTING)
			j2 = build_pdc_journal_entry_data(doc, WORKFLOW_REGISTERED, WORKFLOW_CLEARED, POSTING)
		self.assertEqual(_party_line_count(j1), 1)
		self.assertEqual(_party_line_count(j2), 1)
		for je in (j1, j2):
			bank_rows = [r for r in je["accounts"] if r.get("account") == _BANK_GL]
			self.assertEqual(len(bank_rows), 1)
			self.assertNotIn("party_type", bank_rows[0])


if __name__ == "__main__":
	unittest.main()
