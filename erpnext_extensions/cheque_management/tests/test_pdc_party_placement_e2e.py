# Copyright (c) 2026, Farbod Siyahpoosh and contributors
# For license information, please see license.txt

"""E2E payload tests: Party only on real Receivable/Payable settlement rows.

Restores the pre-ddde37c accounting contract. Party must not be mirrored onto
CIH, Under Collection, clearing, bank, or other internal accounts.
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
from erpnext_extensions.cheque_management.pdc_allocation import ALLOCATION_MODE_ADVANCE
from erpnext_extensions.cheque_management.pdc_workflow_state_machine import (
	CHEQUE_DIRECTION_PAYABLE,
	CHEQUE_DIRECTION_RECEIVABLE,
	WORKFLOW_BOUNCED,
	WORKFLOW_CLEARED,
	WORKFLOW_DRAFT,
	WORKFLOW_ENDORSED,
	WORKFLOW_ISSUED,
	WORKFLOW_REGISTERED,
	WORKFLOW_RETURNED,
	WORKFLOW_SENT_TO_BANK,
)

POSTING = date(2026, 9, 1)
_BANK = "ACC-BANK"

_SETTINGS = {
	"default_cheques_in_hand_account": "ACC-CIH",
	"default_cheques_in_clearing_account": "ACC-CLR",
	"default_payable_cheque_account": "ACC-POOL",
	"default_protested_account": "ACC-PROT",
	"default_endorsement_account": "ACC-ENDORSE",
}


def _has_party(row: dict) -> bool:
	return bool(row.get("party_type") or row.get("party"))


def _assert_no_party(testcase: unittest.TestCase, row: dict) -> None:
	testcase.assertFalse(_has_party(row), row)
	testcase.assertNotIn("party_type", row)
	testcase.assertNotIn("party", row)


def _bank_rows(rows, bank_gl: str = _BANK):
	return [r for r in rows if r.get("account") == bank_gl]


def _non_bank_rows(rows, bank_gl: str = _BANK):
	return [r for r in rows if r.get("account") != bank_gl]


class TestPDCPartyPlacementE2E(unittest.TestCase):
	def test_01_receivable_register_party_only_on_ar(self) -> None:
		doc = SimpleNamespace(
			company="_TC",
			cheque_direction=CHEQUE_DIRECTION_RECEIVABLE,
			party_type="Customer",
			party="CUST-1",
			cheque_amount=500.0,
			cheque_no="R-01",
			account_paid_to="ACC-CIH",
			account_paid_from="ACC-AR",
			bank_account="BA-1",
			allocation_mode="direct_settlement",
		)
		with (
			patch.object(pdc_mod, "_get_pdc_settings_for_company", return_value=dict(_SETTINGS)),
			patch.object(pdc_mod, "_get_party_account_or_company_default", return_value="ACC-PARTY"),
			patch.object(pdc_mod, "_pdc_bank_gl_account", return_value=_BANK),
			patch.object(pdc_mod, "frappe") as mf,
		):
			mf._ = lambda s: s
			je = build_pdc_journal_entry_data(doc, WORKFLOW_DRAFT, WORKFLOW_REGISTERED, POSTING)
		dr, cr = je["accounts"]
		self.assertEqual(dr["account"], "ACC-CIH")
		_assert_no_party(self, dr)
		self.assertEqual(cr["account"], "ACC-AR")
		self.assertEqual(cr.get("party_type"), "Customer")
		self.assertEqual(cr.get("party"), "CUST-1")

	def test_02_payable_register_party_only_on_ap(self) -> None:
		doc = SimpleNamespace(
			company="_TC",
			cheque_direction=CHEQUE_DIRECTION_PAYABLE,
			party_type="Supplier",
			party="SUP-1",
			cheque_amount=500.0,
			cheque_no="P-01",
			account_paid_to="ACC-AP",
			account_paid_from=None,
			bank_account="BA-1",
			allocation_mode="direct_settlement",
		)
		with (
			patch.object(pdc_mod, "_get_pdc_settings_for_company", return_value=dict(_SETTINGS)),
			patch.object(pdc_mod, "_get_party_account_or_company_default", return_value="ACC-PARTY"),
			patch.object(pdc_mod, "_pdc_bank_gl_account", return_value=_BANK),
			patch.object(pdc_mod, "frappe") as mf,
		):
			mf._ = lambda s: s
			je = build_pdc_journal_entry_data(doc, WORKFLOW_DRAFT, WORKFLOW_REGISTERED, POSTING)
		dr, cr = je["accounts"]
		self.assertEqual(dr.get("party_type"), "Supplier")
		self.assertEqual(dr.get("party"), "SUP-1")
		_assert_no_party(self, cr)

	def test_03_send_to_bank_no_party_on_either_row(self) -> None:
		doc = SimpleNamespace(
			company="_TC",
			cheque_direction=CHEQUE_DIRECTION_RECEIVABLE,
			party_type="Customer",
			party="CUST-1",
			cheque_amount=500.0,
			cheque_no="R-03",
			account_paid_to="ACC-CIH",
			account_paid_from="ACC-AR",
			bank_account="BA-1",
		)
		with (
			patch.object(pdc_mod, "_get_pdc_settings_for_company", return_value=dict(_SETTINGS)),
			patch.object(pdc_mod, "_get_party_account_or_company_default", return_value="ACC-PARTY"),
			patch.object(pdc_mod, "_pdc_bank_gl_account", return_value=_BANK),
			patch.object(pdc_mod, "frappe") as mf,
		):
			mf._ = lambda s: s
			je = build_pdc_journal_entry_data(doc, WORKFLOW_REGISTERED, WORKFLOW_SENT_TO_BANK, POSTING)
		for row in je["accounts"]:
			_assert_no_party(self, row)

	def test_04_bounce_no_party_on_either_row(self) -> None:
		doc = SimpleNamespace(
			company="_TC",
			cheque_direction=CHEQUE_DIRECTION_RECEIVABLE,
			party_type="Customer",
			party="CUST-1",
			cheque_amount=500.0,
			cheque_no="R-04",
			account_paid_to="ACC-CIH",
			account_paid_from="ACC-AR",
			bank_account="BA-1",
		)
		with (
			patch.object(pdc_mod, "_get_pdc_settings_for_company", return_value=dict(_SETTINGS)),
			patch.object(pdc_mod, "_get_party_account_or_company_default", return_value="ACC-PARTY"),
			patch.object(pdc_mod, "_pdc_bank_gl_account", return_value=_BANK),
			patch.object(pdc_mod, "frappe") as mf,
		):
			mf._ = lambda s: s
			je = build_pdc_journal_entry_data(doc, WORKFLOW_SENT_TO_BANK, WORKFLOW_BOUNCED, POSTING)
		for row in je["accounts"]:
			_assert_no_party(self, row)

	def test_05_receivable_return_party_only_on_ar(self) -> None:
		doc = SimpleNamespace(
			company="_TC",
			cheque_direction=CHEQUE_DIRECTION_RECEIVABLE,
			party_type="Customer",
			party="CUST-1",
			cheque_amount=500.0,
			cheque_no="R-05",
			account_paid_to="ACC-CIH",
			account_paid_from="ACC-AR",
			bank_account="BA-1",
		)
		with (
			patch.object(pdc_mod, "_get_pdc_settings_for_company", return_value=dict(_SETTINGS)),
			patch.object(pdc_mod, "_get_party_account_or_company_default", return_value="ACC-PARTY"),
			patch.object(pdc_mod, "_pdc_bank_gl_account", return_value=_BANK),
			patch.object(pdc_mod, "frappe") as mf,
		):
			mf._ = lambda s: s
			je = build_pdc_journal_entry_data(doc, WORKFLOW_REGISTERED, WORKFLOW_RETURNED, POSTING)
		dr, cr = je["accounts"]
		self.assertEqual(dr.get("party_type"), "Customer")
		self.assertEqual(dr.get("party"), "CUST-1")
		self.assertEqual(cr["account"], "ACC-CIH")
		_assert_no_party(self, cr)

	def test_06_payable_return_party_only_on_ap(self) -> None:
		doc = SimpleNamespace(
			company="_TC",
			cheque_direction=CHEQUE_DIRECTION_PAYABLE,
			party_type="Supplier",
			party="SUP-1",
			cheque_amount=500.0,
			cheque_no="P-06",
			account_paid_to="ACC-AP",
			bank_account="BA-1",
		)
		with (
			patch.object(pdc_mod, "_get_pdc_settings_for_company", return_value=dict(_SETTINGS)),
			patch.object(pdc_mod, "_get_party_account_or_company_default", return_value="ACC-PARTY"),
			patch.object(pdc_mod, "_pdc_bank_gl_account", return_value=_BANK),
			patch.object(pdc_mod, "frappe") as mf,
		):
			mf._ = lambda s: s
			je = build_pdc_journal_entry_data(doc, WORKFLOW_ISSUED, WORKFLOW_RETURNED, POSTING)
		# Party only on the AP settlement row; internal cheque row stays clean.
		party_rows = [r for r in je["accounts"] if _has_party(r)]
		internal_rows = [r for r in je["accounts"] if not _has_party(r)]
		self.assertEqual(len(party_rows), 1)
		self.assertEqual(party_rows[0].get("party_type"), "Supplier")
		self.assertEqual(party_rows[0].get("party"), "SUP-1")
		self.assertGreaterEqual(len(internal_rows), 1)

	def test_07_advance_recognition_party_only_on_advance_credit(self) -> None:
		doc = SimpleNamespace(
			company="_TC",
			cheque_direction=CHEQUE_DIRECTION_RECEIVABLE,
			party_type="Customer",
			party="CUST-1",
			cheque_amount=500.0,
			cheque_no="R-07",
			account_paid_to="ACC-CIH",
			account_paid_from="ACC-AR",
			bank_account="BA-1",
			allocation_mode=ALLOCATION_MODE_ADVANCE,
			recognition_je_posted=0,
			effective_stage_for_advance_recognition="register",
			advance_account=None,
		)
		with (
			patch.object(pdc_mod, "_get_pdc_settings_for_company", return_value=dict(_SETTINGS)),
			patch.object(pdc_mod, "_get_party_account_or_company_default", return_value="ACC-PARTY"),
			patch.object(pdc_mod, "_pdc_bank_gl_account", return_value=_BANK),
			patch.object(pdc_mod, "_company_default_advance_received_account", return_value="ACC-ADV-REC"),
			patch.object(pdc_mod, "frappe") as mf,
		):
			mf._ = lambda s: s
			je = build_pdc_journal_entry_data(doc, WORKFLOW_DRAFT, WORKFLOW_REGISTERED, POSTING)
		self.assertIsNotNone(je)
		dr, cr = je["accounts"]
		_assert_no_party(self, dr)
		self.assertEqual(cr.get("party_type"), "Customer")
		self.assertEqual(cr.get("party"), "CUST-1")

	def test_08_receivable_clear_no_party_on_any_row(self) -> None:
		doc = SimpleNamespace(
			company="_TC",
			cheque_direction=CHEQUE_DIRECTION_RECEIVABLE,
			party_type="Customer",
			party="CUST-1",
			cheque_amount=500.0,
			cheque_no="R-08",
			account_paid_to="ACC-CIH",
			account_paid_from="ACC-AR",
			bank_account="BA-1",
		)
		with (
			patch.object(pdc_mod, "_get_pdc_settings_for_company", return_value=dict(_SETTINGS)),
			patch.object(pdc_mod, "_get_party_account_or_company_default", return_value="ACC-PARTY"),
			patch.object(pdc_mod, "_pdc_bank_gl_account", return_value=_BANK),
			patch.object(pdc_mod, "frappe") as mf,
		):
			mf._ = lambda s: s
			je = build_pdc_journal_entry_data(doc, WORKFLOW_REGISTERED, WORKFLOW_CLEARED, POSTING)
		rows = je["accounts"]
		self.assertEqual(len(_bank_rows(rows)), 1)
		for row in rows:
			_assert_no_party(self, row)
		self.assertEqual(len(_non_bank_rows(rows)), 1)

	def test_09_payable_clear_no_party_on_pool_or_bank(self) -> None:
		doc = SimpleNamespace(
			company="_TC",
			cheque_direction=CHEQUE_DIRECTION_PAYABLE,
			party_type="Supplier",
			party="SUP-1",
			cheque_amount=500.0,
			cheque_no="P-09",
			account_paid_to="ACC-AP",
			bank_account="BA-1",
		)
		with (
			patch.object(pdc_mod, "_get_pdc_settings_for_company", return_value=dict(_SETTINGS)),
			patch.object(pdc_mod, "_get_party_account_or_company_default", return_value="ACC-PARTY"),
			patch.object(pdc_mod, "_pdc_bank_gl_account", return_value=_BANK),
			patch.object(pdc_mod, "frappe") as mf,
		):
			mf._ = lambda s: s
			je = build_pdc_journal_entry_data(doc, WORKFLOW_ISSUED, WORKFLOW_CLEARED, POSTING)
		for row in je["accounts"]:
			_assert_no_party(self, row)

	def test_endorsement_no_drawer_mirror_internal_accounts_party_free(self) -> None:
		doc = SimpleNamespace(
			company="_TC",
			cheque_direction=CHEQUE_DIRECTION_RECEIVABLE,
			party_type="Customer",
			party="CUST-DRAWER",
			cheque_amount=500.0,
			cheque_no="R-END",
			account_paid_to="ACC-CIH",
			account_paid_from="ACC-AR",
			bank_account="BA-1",
			holder_party_type="Customer",
			holder_party="CUST-HOLDER",
			endorsement_settlement_account=None,
		)
		with (
			patch.object(pdc_mod, "_get_pdc_settings_for_company", return_value=dict(_SETTINGS)),
			patch.object(pdc_mod, "_get_party_account_or_company_default", return_value="ACC-HOLDER-AR"),
			patch.object(pdc_mod, "_pdc_bank_gl_account", return_value=_BANK),
			patch.object(pdc_mod, "frappe") as mf,
		):
			mf._ = lambda s: s
			je = build_pdc_journal_entry_data(doc, WORKFLOW_REGISTERED, WORKFLOW_ENDORSED, POSTING)
		for row in je["accounts"]:
			self.assertNotEqual(row.get("party"), "CUST-DRAWER")
		dr, cr = je["accounts"]
		self.assertEqual(dr["account"], "ACC-ENDORSE")
		_assert_no_party(self, dr)
		_assert_no_party(self, cr)


if __name__ == "__main__":
	unittest.main()
