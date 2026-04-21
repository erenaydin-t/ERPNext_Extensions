# Copyright (c) 2026, Farbod Siyahpoosh and contributors
# For license information, please see license.txt

"""End-to-end **Payable PDC** scenario tests (payload + status; no live GL posting).

Exercises accounting-relevant transitions:

1. Draft → Registered (supplier / PI settlement JE)
2. Registered → Issued (no accounting document)
3. Issued → Cleared
4. Issued → Returned
5. Issued → Cancelled

Verifies:

* ``cheque_status`` from ``map_workflow_state_to_cheque_status``
* ``build_pdc_journal_entry_data`` account lines per edge (where policy is ``journal_entry``)
* Party dimensions only where policy requires; **none** on **Issued → Cleared**
* Company **Bank** GL (``ACC-BANK``) appears **only** on **Issued → Cleared**

Run from bench root::

    ./env/bin/python -m unittest erpnext_extensions.cheque_management.tests.test_pdc_payable_e2e_scenario -v
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
from erpnext_extensions.cheque_management.pdc_workflow_state_machine import (
	CHEQUE_DIRECTION_PAYABLE,
	PDC_ACCOUNTING_JOURNAL_ENTRY,
	PDC_ACCOUNTING_NO_DOCUMENT,
	WORKFLOW_CANCELLED,
	WORKFLOW_CLEARED,
	WORKFLOW_DRAFT,
	WORKFLOW_ISSUED,
	WORKFLOW_REGISTERED,
	WORKFLOW_RETURNED,
	get_pdc_accounting_decision,
)
from erpnext_extensions.cheque_management.pdc_workflow_to_cheque_status import (
	CHEQUE_STATUS_CANCELLED,
	CHEQUE_STATUS_CLEARED,
	CHEQUE_STATUS_DRAFT,
	CHEQUE_STATUS_ISSUED,
	CHEQUE_STATUS_RETURNED_FROM_PAYEE,
	map_workflow_state_to_cheque_status,
)

POSTING = date(2026, 8, 1)

_BANK_GL = "ACC-BANK"

_SETTINGS: dict = {
	"default_cheques_in_hand_account": "ACC-CIH",
	"default_cheques_in_clearing_account": "ACC-CLR",
	"default_payable_cheque_account": "ACC-POOL",
	"default_protested_account": "ACC-PROT",
	"default_endorsement_account": None,
}


def _base_doc() -> SimpleNamespace:
	return SimpleNamespace(
		company="_TC",
		cheque_direction=CHEQUE_DIRECTION_PAYABLE,
		party_type="Supplier",
		party="SUP-1",
		cheque_amount=1000.0,
		cheque_no="E2E-P-001",
		account_paid_to="ACC-AP-DOC",
		account_paid_from=None,
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


class TestPayablePDCEndToEndScenario(unittest.TestCase):
	"""Payable chain: status ladder + JE shapes + bank only on Issued → Cleared."""

	def test_cheque_status_for_each_target_state(self) -> None:
		cases = [
			(WORKFLOW_DRAFT, CHEQUE_STATUS_DRAFT),
			(WORKFLOW_REGISTERED, CHEQUE_STATUS_DRAFT),
			(WORKFLOW_ISSUED, CHEQUE_STATUS_ISSUED),
			(WORKFLOW_CLEARED, CHEQUE_STATUS_CLEARED),
			(WORKFLOW_RETURNED, CHEQUE_STATUS_RETURNED_FROM_PAYEE),
			(WORKFLOW_CANCELLED, CHEQUE_STATUS_CANCELLED),
		]
		for ws, expected in cases:
			with self.subTest(workflow_state=ws):
				self.assertEqual(
					map_workflow_state_to_cheque_status(CHEQUE_DIRECTION_PAYABLE, ws),
					expected,
				)

	def test_draft_to_registered_is_settlement_je(self) -> None:
		"""Payable register posts supplier settlement (Draft → Registered)."""
		self.assertEqual(
			get_pdc_accounting_decision(CHEQUE_DIRECTION_PAYABLE, WORKFLOW_DRAFT, WORKFLOW_REGISTERED),
			PDC_ACCOUNTING_JOURNAL_ENTRY,
		)
		doc = _base_doc()
		with (
			patch.object(pdc_mod, "_get_pdc_settings_for_company", return_value=dict(_SETTINGS)),
			patch.object(pdc_mod, "_get_party_account_or_company_default", return_value="ACC-AP-RESOLVED"),
			patch.object(pdc_mod, "_pdc_bank_gl_account", return_value=_BANK_GL),
			patch.object(pdc_mod, "frappe") as mf,
		):
			mf._ = lambda s: s
			je = build_pdc_journal_entry_data(doc, WORKFLOW_DRAFT, WORKFLOW_REGISTERED, POSTING)
		self.assertIsNotNone(je)
		self.assertEqual(
			map_workflow_state_to_cheque_status(CHEQUE_DIRECTION_PAYABLE, WORKFLOW_REGISTERED),
			CHEQUE_STATUS_DRAFT,
		)

	def test_registered_to_issued_is_no_document_no_je(self) -> None:
		self.assertEqual(
			get_pdc_accounting_decision(CHEQUE_DIRECTION_PAYABLE, WORKFLOW_REGISTERED, WORKFLOW_ISSUED),
			PDC_ACCOUNTING_NO_DOCUMENT,
		)
		doc = _base_doc()
		with (
			patch.object(pdc_mod, "_get_pdc_settings_for_company", return_value=dict(_SETTINGS)),
			patch.object(pdc_mod, "_get_party_account_or_company_default", return_value="ACC-AP-RESOLVED"),
			patch.object(pdc_mod, "_pdc_bank_gl_account", return_value=_BANK_GL),
			patch.object(pdc_mod, "frappe") as mf,
		):
			mf._ = lambda s: s
			je = build_pdc_journal_entry_data(doc, WORKFLOW_REGISTERED, WORKFLOW_ISSUED, POSTING)
		self.assertIsNone(je)

	def test_draft_to_registered_dr_party_ap_cr_pool_one_party_no_bank(self) -> None:
		doc = _base_doc()
		with (
			patch.object(pdc_mod, "_get_pdc_settings_for_company", return_value=dict(_SETTINGS)),
			patch.object(pdc_mod, "_get_party_account_or_company_default", return_value="ACC-AP-RESOLVED"),
			patch.object(pdc_mod, "_pdc_bank_gl_account", return_value=_BANK_GL),
			patch.object(pdc_mod, "frappe") as mf,
		):
			mf._ = lambda s: s
			je = build_pdc_journal_entry_data(doc, WORKFLOW_DRAFT, WORKFLOW_REGISTERED, POSTING)
		self.assertIsNotNone(je)
		self.assertEqual(_party_line_count(je), 1)
		self.assertEqual(_bank_gl_line_count(je), 0)
		dr, cr = je["accounts"]
		self.assertEqual(dr["account"], "ACC-AP-DOC")
		self.assertEqual(dr.get("party_type"), "Supplier")
		self.assertEqual(dr.get("party"), "SUP-1")
		self.assertNotIn("reference_type", dr)
		self.assertEqual(cr["account"], "ACC-POOL")
		self.assertNotIn("party_type", cr)

	def test_issued_to_cleared_dr_pool_cr_bank_no_party(self) -> None:
		doc = _base_doc()
		with (
			patch.object(pdc_mod, "_get_pdc_settings_for_company", return_value=dict(_SETTINGS)),
			patch.object(pdc_mod, "_get_party_account_or_company_default", return_value="ACC-AP-RESOLVED"),
			patch.object(pdc_mod, "_pdc_bank_gl_account", return_value=_BANK_GL),
			patch.object(pdc_mod, "frappe") as mf,
		):
			mf._ = lambda s: s
			je = build_pdc_journal_entry_data(doc, WORKFLOW_ISSUED, WORKFLOW_CLEARED, POSTING)
		self.assertIsNotNone(je)
		self.assertEqual(je["voucher_type"], "Bank Entry")
		self.assertEqual(_party_line_count(je), 0)
		self.assertEqual(_bank_gl_line_count(je), 1)
		dr, cr = je["accounts"]
		self.assertEqual(dr["account"], "ACC-POOL")
		self.assertEqual(cr["account"], _BANK_GL)

	def test_issued_to_returned_dr_pool_cr_ap_one_party_no_bank(self) -> None:
		doc = _base_doc()
		with (
			patch.object(pdc_mod, "_get_pdc_settings_for_company", return_value=dict(_SETTINGS)),
			patch.object(pdc_mod, "_get_party_account_or_company_default", return_value="ACC-AP-RESOLVED"),
			patch.object(pdc_mod, "_pdc_bank_gl_account", return_value=_BANK_GL),
			patch.object(pdc_mod, "frappe") as mf,
		):
			mf._ = lambda s: s
			je = build_pdc_journal_entry_data(doc, WORKFLOW_ISSUED, WORKFLOW_RETURNED, POSTING)
		self.assertIsNotNone(je)
		self.assertEqual(_party_line_count(je), 1)
		self.assertEqual(_bank_gl_line_count(je), 0)
		dr, cr = je["accounts"]
		self.assertEqual(dr["account"], "ACC-POOL")
		self.assertEqual(cr["account"], "ACC-AP-DOC")
		self.assertEqual(cr.get("party_type"), "Supplier")
		self.assertEqual(cr.get("party"), "SUP-1")

	def test_issued_to_cancelled_dr_pool_cr_ap_one_party_no_bank(self) -> None:
		doc = _base_doc()
		with (
			patch.object(pdc_mod, "_get_pdc_settings_for_company", return_value=dict(_SETTINGS)),
			patch.object(pdc_mod, "_get_party_account_or_company_default", return_value="ACC-AP-RESOLVED"),
			patch.object(pdc_mod, "_pdc_bank_gl_account", return_value=_BANK_GL),
			patch.object(pdc_mod, "frappe") as mf,
		):
			mf._ = lambda s: s
			je = build_pdc_journal_entry_data(doc, WORKFLOW_ISSUED, WORKFLOW_CANCELLED, POSTING)
		self.assertIsNotNone(je)
		self.assertEqual(_party_line_count(je), 1)
		self.assertEqual(_bank_gl_line_count(je), 0)
		dr, cr = je["accounts"]
		self.assertEqual(dr["account"], "ACC-POOL")
		self.assertEqual(cr["account"], "ACC-AP-DOC")
		self.assertEqual(cr.get("party_type"), "Supplier")

	def test_bank_gl_only_on_issued_to_cleared(self) -> None:
		"""Bank company ledger appears only on Issued → Cleared; not on register / issue / return / cancel."""
		doc = _base_doc()
		with (
			patch.object(pdc_mod, "_get_pdc_settings_for_company", return_value=dict(_SETTINGS)),
			patch.object(pdc_mod, "_get_party_account_or_company_default", return_value="ACC-AP-RESOLVED"),
			patch.object(pdc_mod, "_pdc_bank_gl_account", return_value=_BANK_GL),
			patch.object(pdc_mod, "frappe") as mf,
		):
			mf._ = lambda s: s
			j_reg = build_pdc_journal_entry_data(doc, WORKFLOW_DRAFT, WORKFLOW_REGISTERED, POSTING)
			j_nop = build_pdc_journal_entry_data(doc, WORKFLOW_REGISTERED, WORKFLOW_ISSUED, POSTING)
			j_clr = build_pdc_journal_entry_data(doc, WORKFLOW_ISSUED, WORKFLOW_CLEARED, POSTING)
			j_ret = build_pdc_journal_entry_data(doc, WORKFLOW_ISSUED, WORKFLOW_RETURNED, POSTING)
			j_can = build_pdc_journal_entry_data(doc, WORKFLOW_ISSUED, WORKFLOW_CANCELLED, POSTING)
		self.assertIsNotNone(j_reg)
		self.assertIsNone(j_nop)
		for label, je in (("register", j_reg), ("return", j_ret), ("cancel", j_can)):
			with self.subTest(step=label):
				self.assertEqual(_bank_gl_line_count(je), 0, f"{label} must not hit bank GL")
		self.assertEqual(_bank_gl_line_count(j_clr), 1)

	def test_clear_je_has_no_party_lines(self) -> None:
		"""Cleared payload must not carry party (pool vs bank only)."""
		doc = _base_doc()
		with (
			patch.object(pdc_mod, "_get_pdc_settings_for_company", return_value=dict(_SETTINGS)),
			patch.object(pdc_mod, "_get_party_account_or_company_default", return_value="ACC-AP-RESOLVED"),
			patch.object(pdc_mod, "_pdc_bank_gl_account", return_value=_BANK_GL),
			patch.object(pdc_mod, "frappe") as mf,
		):
			mf._ = lambda s: s
			je = build_pdc_journal_entry_data(doc, WORKFLOW_ISSUED, WORKFLOW_CLEARED, POSTING)
		self.assertEqual(_party_line_count(je), 0)

	def test_draft_to_registered_splits_party_debit_per_pi_when_slices_provided(self) -> None:
		"""Multiple Purchase Invoices → multiple Dr AP lines with reference_name; one Cr pool."""
		doc = _base_doc()
		with (
			patch.object(pdc_mod, "_get_pdc_settings_for_company", return_value=dict(_SETTINGS)),
			patch.object(pdc_mod, "_get_party_account_or_company_default", return_value="ACC-AP-DOC"),
			patch.object(pdc_mod, "_pdc_bank_gl_account", return_value=_BANK_GL),
			patch.object(
				pdc_mod,
				"payable_purchase_invoice_settlement_slices",
				return_value=[("PINV-A", 400.0), ("PINV-B", 600.0)],
			),
			patch.object(pdc_mod, "frappe") as mf,
		):
			mf._ = lambda s: s
			je = build_pdc_journal_entry_data(doc, WORKFLOW_DRAFT, WORKFLOW_REGISTERED, POSTING)
		self.assertIsNotNone(je)
		rows = je["accounts"]
		self.assertEqual(len(rows), 3)
		self.assertEqual(rows[0]["debit_in_account_currency"], 400.0)
		self.assertEqual(rows[0].get("reference_type"), "Purchase Invoice")
		self.assertEqual(rows[0].get("reference_name"), "PINV-A")
		self.assertEqual(rows[1]["debit_in_account_currency"], 600.0)
		self.assertEqual(rows[1].get("reference_name"), "PINV-B")
		self.assertEqual(rows[2]["account"], "ACC-POOL")
		self.assertEqual(rows[2]["credit_in_account_currency"], 1000.0)
		self.assertNotIn("reference_type", rows[2])


if __name__ == "__main__":
	unittest.main()
