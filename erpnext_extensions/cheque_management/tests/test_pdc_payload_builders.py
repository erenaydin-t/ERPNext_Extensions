# Copyright (c) 2025, Farbod Siyahpoosh and contributors
# For license information, please see license.txt

"""Unit tests for **Journal Entry** payload builder in ``post_dated_cheque.py``.

Requires a bench Python environment (``frappe`` + ``erpnext``) because the builders
import the Frappe stack. From bench root::

    ./env/bin/python -m unittest erpnext_extensions.cheque_management.tests.test_pdc_payload_builders -v
"""

from __future__ import annotations

import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from frappe.exceptions import ValidationError

import erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque as pdc
from erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque import (
	PDC_JE_REMARK_CLEAR_PAYABLE_CHEQUE,
	PDC_JE_REMARK_CLEAR_RECEIVABLE_CLEARING,
	PDC_JE_REMARK_CLEAR_RECEIVABLE_LEGAL,
	PDC_JE_REMARK_CLEAR_RECEIVABLE_REGISTERED,
	PDC_JE_REMARK_REGISTER_PAYABLE_CHEQUE,
	PDC_JE_REMARK_REGISTER_RECEIVABLE_CHEQUE,
	PDC_JE_REMARK_SEND_RECEIVABLE_CHEQUE_TO_BANK,
	build_pdc_journal_entry_data,
	build_pdc_journal_entry_payload,
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
	WORKFLOW_REPLACED,
	WORKFLOW_RETURNED,
	WORKFLOW_SENT_TO_BANK,
	WORKFLOW_UNDER_LEGAL_ACTION,
)

POSTING = date(2026, 4, 1)

_SETTINGS_BASE: dict = {
	"default_cheques_in_hand_account": "ACC-CIH-SET",
	"default_cheques_in_clearing_account": "ACC-CLEAR-SET",
	"default_payable_cheque_account": "ACC-PAY-POOL-SET",
	"default_protested_account": "ACC-PROTEST-SET",
	"default_endorsement_account": None,
}


def _doc(**overrides):
	fields = {
		"company": "_TC",
		"cheque_direction": CHEQUE_DIRECTION_RECEIVABLE,
		"party_type": "Customer",
		"party": "CUST-1",
		"cheque_amount": 1000.0,
		"cheque_no": "CHK-9",
		"account_paid_to": "ACC-CIH-DOC",
		"account_paid_from": "ACC-AR-DOC",
		"bank_account": "BA-1",
		"holder_party_type": None,
		"holder_party": None,
	}
	fields.update(overrides)
	return SimpleNamespace(**fields)


class TestPDCJournalEntryPayloadBuilder(unittest.TestCase):
	def test_payload_alias_is_same_callable(self) -> None:
		self.assertIs(build_pdc_journal_entry_payload, build_pdc_journal_entry_data)

	def test_receivable_draft_to_registered_accounts_and_remarks(self) -> None:
		doc = _doc()
		with (
			patch.object(pdc, "_get_pdc_settings_for_company", return_value=dict(_SETTINGS_BASE)),
			patch.object(pdc, "_get_party_account_or_company_default", return_value="ACC-PARTY-FALLBACK"),
			patch.object(pdc, "frappe") as mf,
		):
			mf._ = lambda s: s
			je = build_pdc_journal_entry_data(doc, WORKFLOW_DRAFT, WORKFLOW_REGISTERED, POSTING)
		self.assertIsNotNone(je)
		assert je is not None
		self.assertEqual(je["voucher_type"], "Journal Entry")
		self.assertEqual(je["posting_date"], POSTING)
		self.assertEqual(je["remarks"], f"{PDC_JE_REMARK_REGISTER_RECEIVABLE_CHEQUE} — CHK-9")
		dr, cr = je["accounts"]
		self.assertEqual(dr["account"], "ACC-CIH-DOC")
		self.assertEqual(dr["debit_in_account_currency"], 1000.0)
		self.assertEqual(cr["account"], "ACC-AR-DOC")
		self.assertEqual(cr["credit_in_account_currency"], 1000.0)
		self.assertEqual(cr.get("party_type"), "Customer")
		self.assertEqual(cr.get("party"), "CUST-1")
		self.assertEqual(dr.get("party_type"), "Customer")
		self.assertEqual(dr.get("party"), "CUST-1")

	def test_receivable_draft_to_registered_splits_party_credit_per_si_when_slices_provided(self) -> None:
		doc = _doc()
		with (
			patch.object(pdc, "_get_pdc_settings_for_company", return_value=dict(_SETTINGS_BASE)),
			patch.object(pdc, "_get_party_account_or_company_default", return_value="ACC-PARTY-FALLBACK"),
			patch.object(
				pdc,
				"receivable_sales_invoice_settlement_slices",
				return_value=[("SINV-A", 400.0), ("SINV-B", 600.0)],
			),
			patch.object(pdc, "frappe") as mf,
		):
			mf._ = lambda s: s
			je = build_pdc_journal_entry_data(doc, WORKFLOW_DRAFT, WORKFLOW_REGISTERED, POSTING)
		assert je is not None
		rows = je["accounts"]
		self.assertEqual(len(rows), 3)
		self.assertEqual(rows[0]["debit_in_account_currency"], 1000.0)
		self.assertEqual(rows[1]["credit_in_account_currency"], 400.0)
		self.assertEqual(rows[1].get("reference_type"), "Sales Invoice")
		self.assertEqual(rows[1].get("reference_name"), "SINV-A")
		self.assertEqual(rows[2]["credit_in_account_currency"], 600.0)
		self.assertEqual(rows[2].get("reference_name"), "SINV-B")

	def test_receivable_registered_to_returned_splits_party_debit_per_si_when_slices_provided(self) -> None:
		doc = _doc()
		with (
			patch.object(pdc, "_get_pdc_settings_for_company", return_value=dict(_SETTINGS_BASE)),
			patch.object(pdc, "_get_party_account_or_company_default", return_value="ACC-PARTY-FALLBACK"),
			patch.object(
				pdc,
				"receivable_sales_invoice_settlement_slices",
				return_value=[("SINV-A", 400.0), ("SINV-B", 600.0)],
			),
			patch.object(pdc, "frappe") as mf,
		):
			mf._ = lambda s: s
			je = build_pdc_journal_entry_data(doc, WORKFLOW_REGISTERED, WORKFLOW_RETURNED, POSTING)
		assert je is not None
		rows = je["accounts"]
		self.assertEqual(len(rows), 3)
		self.assertEqual(rows[0]["debit_in_account_currency"], 400.0)
		self.assertEqual(rows[0].get("reference_type"), "Sales Invoice")
		self.assertEqual(rows[1]["debit_in_account_currency"], 600.0)
		self.assertEqual(rows[1].get("reference_name"), "SINV-B")
		self.assertEqual(rows[2]["credit_in_account_currency"], 1000.0)

	def test_receivable_draft_to_registered_uses_party_fallback_when_no_paid_from(self) -> None:
		doc = _doc(account_paid_from=None)
		with (
			patch.object(pdc, "_get_pdc_settings_for_company", return_value=dict(_SETTINGS_BASE)),
			patch.object(pdc, "_get_party_account_or_company_default", return_value="ONLY-PARTY-AR"),
			patch.object(pdc, "frappe") as mf,
		):
			mf._ = lambda s: s
			je = build_pdc_journal_entry_data(doc, WORKFLOW_DRAFT, WORKFLOW_REGISTERED, POSTING)
		assert je is not None
		self.assertEqual(je["accounts"][1]["account"], "ONLY-PARTY-AR")

	def test_receivable_registered_to_sent_bank(self) -> None:
		doc = _doc()
		with (
			patch.object(pdc, "_get_pdc_settings_for_company", return_value=dict(_SETTINGS_BASE)),
			patch.object(pdc, "_get_party_account_or_company_default", return_value="ACC-PARTY-FALLBACK"),
			patch.object(pdc, "frappe") as mf,
		):
			mf._ = lambda s: s
			je = build_pdc_journal_entry_data(doc, WORKFLOW_REGISTERED, WORKFLOW_SENT_TO_BANK, POSTING)
		assert je is not None
		self.assertEqual(je["remarks"], f"{PDC_JE_REMARK_SEND_RECEIVABLE_CHEQUE_TO_BANK} — CHK-9")
		dr, cr = je["accounts"]
		self.assertEqual(dr["account"], "ACC-CLEAR-SET")
		self.assertEqual(cr["account"], "ACC-CIH-DOC")

	def test_receivable_sent_bank_to_bounced_party_on_both_rows(self) -> None:
		doc = _doc()
		with (
			patch.object(pdc, "_get_pdc_settings_for_company", return_value=dict(_SETTINGS_BASE)),
			patch.object(pdc, "_get_party_account_or_company_default", return_value="ACC-PARTY-FALLBACK"),
			patch.object(pdc, "frappe") as mf,
		):
			mf._ = lambda s: s
			je = build_pdc_journal_entry_data(doc, WORKFLOW_SENT_TO_BANK, WORKFLOW_BOUNCED, POSTING)
		assert je is not None
		dr, cr = je["accounts"]
		self.assertEqual(dr["account"], "ACC-PROTEST-SET")
		self.assertEqual(dr.get("party"), "CUST-1")
		self.assertEqual(cr["account"], "ACC-CLEAR-SET")
		self.assertEqual(cr.get("party"), "CUST-1")

	def test_receivable_sent_bank_to_bounced_without_protested_uses_cheques_in_hand(self) -> None:
		doc = _doc()
		st = dict(_SETTINGS_BASE)
		st["default_protested_account"] = None
		with (
			patch.object(pdc, "_get_pdc_settings_for_company", return_value=st),
			patch.object(pdc, "_get_party_account_or_company_default", return_value="ACC-PARTY-FALLBACK"),
			patch.object(pdc, "frappe") as mf,
		):
			mf._ = lambda s: s
			je = build_pdc_journal_entry_data(doc, WORKFLOW_SENT_TO_BANK, WORKFLOW_BOUNCED, POSTING)
		assert je is not None
		dr = je["accounts"][0]
		# Resolver prefers PDC Settings cheques-in-hand over ``account_paid_to``.
		self.assertEqual(dr["account"], "ACC-CIH-SET")
		self.assertEqual(dr.get("party"), "CUST-1")

	def test_payable_draft_to_registered(self) -> None:
		doc = _doc(cheque_direction=CHEQUE_DIRECTION_PAYABLE, account_paid_from=None)
		with (
			patch.object(pdc, "_get_pdc_settings_for_company", return_value=dict(_SETTINGS_BASE)),
			patch.object(pdc, "_get_party_account_or_company_default", return_value="ACC-PARTY-AP"),
			patch.object(pdc, "frappe") as mf,
		):
			mf._ = lambda s: s
			je = build_pdc_journal_entry_data(doc, WORKFLOW_DRAFT, WORKFLOW_REGISTERED, POSTING)
		assert je is not None
		self.assertEqual(je["remarks"], f"{PDC_JE_REMARK_REGISTER_PAYABLE_CHEQUE} — CHK-9")
		dr, cr = je["accounts"]
		self.assertEqual(dr["account"], "ACC-CIH-DOC")
		self.assertEqual(dr.get("party_type"), "Customer")
		self.assertEqual(dr.get("party"), "CUST-1")
		self.assertEqual(cr["account"], "ACC-PAY-POOL-SET")
		self.assertEqual(cr.get("party_type"), "Customer")
		self.assertEqual(cr.get("party"), "CUST-1")

	def test_advance_mode_payable_po_recognition_posts_on_register_and_sets_marker(self) -> None:
		doc = _doc(
			cheque_direction=CHEQUE_DIRECTION_PAYABLE,
			allocation_mode=ALLOCATION_MODE_ADVANCE,
			effective_stage_for_advance_recognition="register",
			party_type="Supplier",
			party="SUP-1",
			account_paid_from=None,
		)
		with (
			patch.object(pdc, "_get_pdc_settings_for_company", return_value=dict(_SETTINGS_BASE)),
			patch.object(pdc, "_company_default_advance_paid_account", return_value="ACC-ADV-PAID"),
			patch.object(pdc, "frappe") as mf,
		):
			mf._ = lambda s: s
			je = build_pdc_journal_entry_data(doc, WORKFLOW_DRAFT, WORKFLOW_REGISTERED, POSTING)
		assert je is not None
		self.assertEqual(int(je.get("set_recognition_je_posted") or 0), 1)
		dr, cr = je["accounts"]
		self.assertEqual(dr["account"], "ACC-ADV-PAID")
		self.assertEqual(dr.get("party_type"), "Supplier")
		self.assertEqual(dr.get("party"), "SUP-1")
		self.assertEqual(cr["account"], "ACC-PAY-POOL-SET")
		self.assertEqual(cr.get("party_type"), "Supplier")
		self.assertEqual(cr.get("party"), "SUP-1")
		self.assertNotIn("reference_type", dr)
		self.assertNotIn("reference_type", cr)

	def test_advance_mode_receivable_so_recognition_posts_on_register_and_sets_marker(self) -> None:
		doc = _doc(
			cheque_direction=CHEQUE_DIRECTION_RECEIVABLE,
			allocation_mode=ALLOCATION_MODE_ADVANCE,
			effective_stage_for_advance_recognition="register",
			party_type="Customer",
			party="CUST-1",
		)
		with (
			patch.object(pdc, "_get_pdc_settings_for_company", return_value=dict(_SETTINGS_BASE)),
			patch.object(pdc, "_company_default_advance_received_account", return_value="ACC-ADV-REC"),
			patch.object(pdc, "_get_party_account_or_company_default", return_value="SHOULD-NOT-USE"),
			patch.object(pdc, "frappe") as mf,
		):
			mf._ = lambda s: s
			je = build_pdc_journal_entry_data(doc, WORKFLOW_DRAFT, WORKFLOW_REGISTERED, POSTING)
		assert je is not None
		self.assertEqual(int(je.get("set_recognition_je_posted") or 0), 1)
		dr, cr = je["accounts"]
		self.assertEqual(dr["account"], "ACC-CIH-DOC")
		self.assertEqual(cr["account"], "ACC-ADV-REC")
		self.assertEqual(dr.get("party_type"), "Customer")
		self.assertEqual(dr.get("party"), "CUST-1")
		self.assertEqual(cr.get("party_type"), "Customer")
		self.assertEqual(cr.get("party"), "CUST-1")
		self.assertNotIn("reference_type", dr)
		self.assertNotIn("reference_type", cr)

	def test_advance_mode_effective_stage_issue_posts_only_on_registered_to_issued(self) -> None:
		doc = _doc(
			cheque_direction=CHEQUE_DIRECTION_PAYABLE,
			allocation_mode=ALLOCATION_MODE_ADVANCE,
			effective_stage_for_advance_recognition="issue",
			party_type="Supplier",
			party="SUP-1",
		)
		with (
			patch.object(pdc, "_get_pdc_settings_for_company", return_value=dict(_SETTINGS_BASE)),
			patch.object(pdc, "_company_default_advance_paid_account", return_value="ACC-ADV-PAID"),
			patch.object(pdc, "frappe") as mf,
		):
			mf._ = lambda s: s
			j_reg = build_pdc_journal_entry_data(doc, WORKFLOW_DRAFT, WORKFLOW_REGISTERED, POSTING)
			j_issue = build_pdc_journal_entry_data(doc, WORKFLOW_REGISTERED, WORKFLOW_ISSUED, POSTING)
		self.assertIsNone(j_reg)
		self.assertIsNotNone(j_issue)

	def test_endorsement_uses_settings_account_when_set(self) -> None:
		st = dict(_SETTINGS_BASE)
		st["default_endorsement_account"] = "ACC-ENDORSE-SET"
		doc = _doc(holder_party_type="Customer", holder_party="HOLD-1")
		with (
			patch.object(pdc, "_get_pdc_settings_for_company", return_value=st),
			patch.object(pdc, "_get_party_account_or_company_default", return_value="SHOULD-NOT-USE"),
			patch.object(pdc, "frappe") as mf,
		):
			mf._ = lambda s: s
			je = build_pdc_journal_entry_data(doc, WORKFLOW_REGISTERED, WORKFLOW_ENDORSED, POSTING)
		assert je is not None
		dr, cr = je["accounts"]
		self.assertEqual(dr["account"], "ACC-ENDORSE-SET")
		self.assertNotIn("party_type", dr)
		self.assertEqual(cr["account"], "ACC-CIH-DOC")

	def test_endorsement_doc_settlement_overrides_settings(self) -> None:
		st = dict(_SETTINGS_BASE)
		st["default_endorsement_account"] = "ACC-ENDORSE-SET"
		doc = _doc(
			holder_party_type="Customer",
			holder_party="HOLD-1",
			endorsement_settlement_account="ACC-ENDORSE-DOC",
		)
		with (
			patch.object(pdc, "_get_pdc_settings_for_company", return_value=st),
			patch.object(pdc, "_get_party_account_or_company_default", return_value="SHOULD-NOT-USE"),
			patch.object(pdc, "frappe") as mf,
		):
			mf._ = lambda s: s
			je = build_pdc_journal_entry_data(doc, WORKFLOW_REGISTERED, WORKFLOW_ENDORSED, POSTING)
		assert je is not None
		dr, _cr = je["accounts"]
		self.assertEqual(dr["account"], "ACC-ENDORSE-DOC")

	def test_endorsement_holder_receivable_when_no_settlement_gl(self) -> None:
		doc = _doc(
			holder_party_type="Customer",
			holder_party="HOLD-OTHER",
		)
		with (
			patch.object(pdc, "_get_pdc_settings_for_company", return_value=dict(_SETTINGS_BASE)),
			patch.object(pdc, "_get_party_account_or_company_default", return_value="ACC-HOLDER-AR"),
			patch.object(pdc, "frappe") as mf,
		):
			mf._ = lambda s: s
			je = build_pdc_journal_entry_data(doc, WORKFLOW_REGISTERED, WORKFLOW_ENDORSED, POSTING)
		assert je is not None
		dr, cr = je["accounts"]
		self.assertEqual(dr["account"], "ACC-HOLDER-AR")
		self.assertEqual(dr.get("party_type"), "Customer")
		self.assertEqual(dr.get("party"), "HOLD-OTHER")
		self.assertNotIn("party_type", cr)

	def test_endorsement_same_holder_without_gl_returns_none(self) -> None:
		doc = _doc(
			holder_party_type="Customer",
			holder_party="CUST-1",
		)
		with (
			patch.object(pdc, "_get_pdc_settings_for_company", return_value=dict(_SETTINGS_BASE)),
			patch.object(pdc, "_get_party_account_or_company_default", return_value="ACC-SHOULD-NOT-CALL"),
			patch.object(pdc, "frappe") as mf,
		):
			mf._ = lambda s: s
			je = build_pdc_journal_entry_data(doc, WORKFLOW_REGISTERED, WORKFLOW_ENDORSED, POSTING)
		self.assertIsNone(je)

	def test_bounced_to_replaced_requires_protested_account(self) -> None:
		doc = _doc()
		st = dict(_SETTINGS_BASE)
		st["default_protested_account"] = None
		with (
			patch.object(pdc, "_get_pdc_settings_for_company", return_value=st),
			patch.object(pdc, "_get_party_account_or_company_default", return_value="ACC-PARTY-FALLBACK"),
			patch.object(pdc, "frappe") as mf,
		):
			mf._ = lambda s: s
			je = build_pdc_journal_entry_data(doc, WORKFLOW_BOUNCED, WORKFLOW_REPLACED, POSTING)
		self.assertIsNone(je)

	def test_returns_none_when_not_journal_entry_decision(self) -> None:
		doc = _doc()
		with (
			patch.object(pdc, "_get_pdc_settings_for_company", return_value=dict(_SETTINGS_BASE)),
			patch.object(pdc, "_get_party_account_or_company_default", return_value="ACC-PARTY-FALLBACK"),
			patch.object(pdc, "frappe") as mf,
		):
			mf._ = lambda s: s
			self.assertIsNone(
				build_pdc_journal_entry_data(doc, WORKFLOW_REGISTERED, WORKFLOW_REPLACED, POSTING)
			)

	def test_receivable_registered_to_cleared_is_journal_entry_bank_vs_in_hand(self) -> None:
		doc = _doc()
		with (
			patch.object(pdc, "_get_pdc_settings_for_company", return_value=dict(_SETTINGS_BASE)),
			patch.object(pdc, "_get_party_account_or_company_default", return_value="ACC-PARTY-FALLBACK"),
			patch.object(pdc, "_pdc_bank_gl_account", return_value="ACC-BANK-GL"),
			patch.object(pdc, "frappe") as mf,
		):
			mf._ = lambda s: s
			je = build_pdc_journal_entry_data(doc, WORKFLOW_REGISTERED, WORKFLOW_CLEARED, POSTING)
		assert je is not None
		self.assertEqual(je["voucher_type"], "Bank Entry")
		dr, cr = je["accounts"]
		self.assertEqual(dr["account"], "ACC-BANK-GL")
		self.assertEqual(cr["account"], "ACC-CIH-DOC")
		self.assertNotIn("party_type", dr)
		self.assertEqual(cr.get("party"), "CUST-1")
		self.assertIn(PDC_JE_REMARK_CLEAR_RECEIVABLE_REGISTERED, je["remarks"])

	def test_returns_none_when_clearing_missing_for_send_to_bank(self) -> None:
		doc = _doc()
		st = dict(_SETTINGS_BASE)
		st["default_cheques_in_clearing_account"] = None
		with (
			patch.object(pdc, "_get_pdc_settings_for_company", return_value=st),
			patch.object(pdc, "_get_party_account_or_company_default", return_value="ACC-PARTY-FALLBACK"),
			patch.object(pdc, "frappe") as mf,
		):
			mf._ = lambda s: s
			self.assertIsNone(
				build_pdc_journal_entry_data(doc, WORKFLOW_REGISTERED, WORKFLOW_SENT_TO_BANK, POSTING)
			)

	def test_receivable_sent_bank_to_cleared_journal_uses_clearing(self) -> None:
		doc = _doc()
		with (
			patch.object(pdc, "_get_pdc_settings_for_company", return_value=dict(_SETTINGS_BASE)),
			patch.object(pdc, "_get_party_account_or_company_default", return_value="ACC-PARTY-FALLBACK"),
			patch.object(pdc, "_pdc_bank_gl_account", return_value="ACC-BANK-GL"),
			patch.object(pdc, "frappe") as mf,
		):
			mf._ = lambda s: s
			je = build_pdc_journal_entry_data(doc, WORKFLOW_SENT_TO_BANK, WORKFLOW_CLEARED, POSTING)
		assert je is not None
		self.assertEqual(je["voucher_type"], "Bank Entry")
		self.assertEqual(je["accounts"][0]["account"], "ACC-BANK-GL")
		self.assertEqual(je["accounts"][1]["account"], "ACC-CLEAR-SET")
		self.assertIn(PDC_JE_REMARK_CLEAR_RECEIVABLE_CLEARING, je["remarks"])

	def test_receivable_under_legal_to_cleared_journal_uses_protested_then_clearing(self) -> None:
		doc = _doc()
		with (
			patch.object(pdc, "_get_pdc_settings_for_company", return_value=dict(_SETTINGS_BASE)),
			patch.object(pdc, "_get_party_account_or_company_default", return_value="ACC-PARTY-FALLBACK"),
			patch.object(pdc, "_pdc_bank_gl_account", return_value="ACC-BANK-GL"),
			patch.object(pdc, "frappe") as mf,
		):
			mf._ = lambda s: s
			je = build_pdc_journal_entry_data(doc, WORKFLOW_UNDER_LEGAL_ACTION, WORKFLOW_CLEARED, POSTING)
		assert je is not None
		self.assertEqual(je["voucher_type"], "Bank Entry")
		self.assertEqual(je["accounts"][1]["account"], "ACC-PROTEST-SET")
		self.assertIn(PDC_JE_REMARK_CLEAR_RECEIVABLE_LEGAL, je["remarks"])
		st = dict(_SETTINGS_BASE)
		st["default_protested_account"] = None
		with (
			patch.object(pdc, "_get_pdc_settings_for_company", return_value=st),
			patch.object(pdc, "_get_party_account_or_company_default", return_value="ACC-PARTY-FALLBACK"),
			patch.object(pdc, "_pdc_bank_gl_account", return_value="ACC-BANK-GL"),
			patch.object(pdc, "frappe") as mf,
		):
			mf._ = lambda s: s
			je2 = build_pdc_journal_entry_data(doc, WORKFLOW_UNDER_LEGAL_ACTION, WORKFLOW_CLEARED, POSTING)
		assert je2 is not None
		self.assertEqual(je2["voucher_type"], "Bank Entry")
		self.assertEqual(je2["accounts"][1]["account"], "ACC-CLEAR-SET")

	def test_payable_issued_to_cleared_journal_dr_pool_with_party_cr_bank_no_party(self) -> None:
		doc = _doc(cheque_direction=CHEQUE_DIRECTION_PAYABLE, account_paid_from=None)
		with (
			patch.object(pdc, "_get_pdc_settings_for_company", return_value=dict(_SETTINGS_BASE)),
			patch.object(pdc, "_pdc_bank_gl_account", return_value="ACC-BANK-GL"),
			patch.object(pdc, "frappe") as mf,
		):
			mf._ = lambda s: s
			je = build_pdc_journal_entry_data(doc, WORKFLOW_ISSUED, WORKFLOW_CLEARED, POSTING)
		assert je is not None
		self.assertEqual(je["voucher_type"], "Bank Entry")
		dr, cr = je["accounts"][0], je["accounts"][1]
		self.assertEqual(dr["account"], "ACC-PAY-POOL-SET")
		self.assertEqual(float(dr.get("debit_in_account_currency") or 0), 1000.0)
		self.assertEqual(cr["account"], "ACC-BANK-GL")
		self.assertEqual(float(cr.get("credit_in_account_currency") or 0), 1000.0)
		self.assertEqual(dr.get("party"), "CUST-1")
		self.assertEqual(dr.get("party_type"), "Customer")
		self.assertNotIn("party_type", cr)
		self.assertNotIn("party", cr)
		self.assertEqual(je["remarks"], f"{PDC_JE_REMARK_CLEAR_PAYABLE_CHEQUE} — CHK-9")

	def test_payable_clear_journal_returns_none_without_bank_gl(self) -> None:
		doc = _doc(cheque_direction=CHEQUE_DIRECTION_PAYABLE)
		with (
			patch.object(pdc, "_get_pdc_settings_for_company", return_value=dict(_SETTINGS_BASE)),
			patch.object(pdc, "_pdc_bank_gl_account", return_value=None),
			patch.object(pdc, "frappe") as mf,
		):
			mf._ = lambda s: s
			self.assertIsNone(build_pdc_journal_entry_data(doc, WORKFLOW_ISSUED, WORKFLOW_CLEARED, POSTING))

	def test_payable_clear_journal_returns_none_without_amount(self) -> None:
		doc = _doc(cheque_direction=CHEQUE_DIRECTION_PAYABLE, cheque_amount=0)
		with (
			patch.object(pdc, "_get_pdc_settings_for_company", return_value=dict(_SETTINGS_BASE)),
			patch.object(pdc, "_pdc_bank_gl_account", return_value="ACC-BANK-GL"),
			patch.object(pdc, "frappe") as mf,
		):
			mf._ = lambda s: s
			self.assertIsNone(build_pdc_journal_entry_data(doc, WORKFLOW_ISSUED, WORKFLOW_CLEARED, POSTING))


class TestPDCClearingBankLedgerValidation(unittest.TestCase):
	"""Clearing JE must use a **Bank** COA account for the PDC company (when Account exists in DB)."""

	@staticmethod
	def _fake_frappe_for_accounts(gcv):
		"""Minimal frappe stand-in so ``db.exists`` / ``get_cached_value`` are deterministic (not MagicMock)."""

		def _exists(doctype: str, name: str | None) -> bool:
			return doctype == "Account" and bool(name)

		def _throw(msg, *args, **kwargs):
			raise ValidationError(msg if isinstance(msg, str) else str(msg))

		return SimpleNamespace(
			_=lambda s: s,
			throw=_throw,
			db=SimpleNamespace(exists=_exists),
			get_cached_value=gcv,
		)

	def test_receivable_clear_rejects_non_bank_ledger(self) -> None:
		doc = _doc()

		def gcv(doctype, name, field, *args, **kwargs):
			if doctype == "Account" and name == "ACC-BANK-GL":
				return {"company": "_TC", "account_type": "Cash"}.get(field)
			if doctype == "Account" and name == "ACC-CIH-DOC":
				return {"account_type": "Stock"}.get(field)
			return None

		fake = self._fake_frappe_for_accounts(gcv)
		with (
			patch.object(pdc, "_get_pdc_settings_for_company", return_value=dict(_SETTINGS_BASE)),
			patch.object(pdc, "_get_party_account_or_company_default", return_value="ACC-PARTY-FALLBACK"),
			patch.object(pdc, "_pdc_bank_gl_account", return_value="ACC-BANK-GL"),
			patch.object(pdc, "frappe", fake),
		):
			with self.assertRaises(ValidationError):
				build_pdc_journal_entry_data(doc, WORKFLOW_REGISTERED, WORKFLOW_CLEARED, POSTING)

	def test_receivable_clear_rejects_bank_gl_wrong_company(self) -> None:
		doc = _doc()

		def gcv(doctype, name, field, *args, **kwargs):
			if doctype == "Account" and name == "ACC-BANK-GL":
				return {"company": "Other Co", "account_type": "Bank"}.get(field)
			if doctype == "Account" and name == "ACC-CIH-DOC":
				return {"account_type": "Stock"}.get(field)
			return None

		fake = self._fake_frappe_for_accounts(gcv)
		with (
			patch.object(pdc, "_get_pdc_settings_for_company", return_value=dict(_SETTINGS_BASE)),
			patch.object(pdc, "_get_party_account_or_company_default", return_value="ACC-PARTY-FALLBACK"),
			patch.object(pdc, "_pdc_bank_gl_account", return_value="ACC-BANK-GL"),
			patch.object(pdc, "frappe", fake),
		):
			with self.assertRaises(ValidationError):
				build_pdc_journal_entry_data(doc, WORKFLOW_REGISTERED, WORKFLOW_CLEARED, POSTING)

	def test_payable_clear_rejects_non_bank_ledger(self) -> None:
		doc = _doc(cheque_direction=CHEQUE_DIRECTION_PAYABLE)

		def gcv(doctype, name, field, *args, **kwargs):
			if doctype == "Account" and name == "ACC-BANK-GL":
				return {"company": "_TC", "account_type": "Cash"}.get(field)
			if doctype == "Account" and name == "ACC-PAY-POOL-SET":
				return {"account_type": "Stock"}.get(field)
			return None

		fake = self._fake_frappe_for_accounts(gcv)
		with (
			patch.object(pdc, "_get_pdc_settings_for_company", return_value=dict(_SETTINGS_BASE)),
			patch.object(pdc, "_pdc_bank_gl_account", return_value="ACC-BANK-GL"),
			patch.object(pdc, "frappe", fake),
		):
			with self.assertRaises(ValidationError):
				build_pdc_journal_entry_data(doc, WORKFLOW_ISSUED, WORKFLOW_CLEARED, POSTING)

	def test_receivable_clear_allows_receivable_intermediary_account_with_party(self) -> None:
		"""Clearing account may be typed Receivable in COA; Party is still required on the non-bank clear line."""
		doc = _doc()
		settings = dict(_SETTINGS_BASE)
		settings["default_cheques_in_clearing_account"] = "ACC-CLEAR-REC"

		def gcv(doctype, name, field, *args, **kwargs):
			if doctype == "Account" and name == "ACC-BANK-GL":
				return {"company": "_TC", "account_type": "Bank"}.get(field)
			if doctype == "Account" and name == "ACC-CLEAR-REC":
				return {"account_type": "Receivable"}.get(field)
			if doctype == "Account" and name == "ACC-CIH-DOC":
				return {"account_type": ""}.get(field)
			return None

		fake = self._fake_frappe_for_accounts(gcv)
		with (
			patch.object(pdc, "_get_pdc_settings_for_company", return_value=settings),
			patch.object(pdc, "_get_party_account_or_company_default", return_value="ACC-PARTY-FALLBACK"),
			patch.object(pdc, "_pdc_bank_gl_account", return_value="ACC-BANK-GL"),
			patch.object(pdc, "frappe", fake),
		):
			je = build_pdc_journal_entry_data(doc, WORKFLOW_SENT_TO_BANK, WORKFLOW_CLEARED, POSTING)
		self.assertIsNotNone(je)
		cr = [r for r in je["accounts"] if r.get("credit_in_account_currency")][0]
		dr = [r for r in je["accounts"] if r.get("debit_in_account_currency")][0]
		self.assertEqual(cr["account"], "ACC-CLEAR-REC")
		self.assertEqual(cr.get("party"), "CUST-1")
		self.assertEqual(cr.get("party_type"), "Customer")
		self.assertNotIn("party_type", dr)
		self.assertNotIn("party", dr)

	def test_receivable_clear_rejects_bank_gl_receivable_account_type(self) -> None:
		doc = _doc()

		def gcv(doctype, name, field, *args, **kwargs):
			if doctype == "Account" and name == "ACC-BANK-GL":
				return {"company": "_TC", "account_type": "Receivable"}.get(field)
			return None

		fake = self._fake_frappe_for_accounts(gcv)
		with (
			patch.object(pdc, "_get_pdc_settings_for_company", return_value=dict(_SETTINGS_BASE)),
			patch.object(pdc, "_pdc_bank_gl_account", return_value="ACC-BANK-GL"),
			patch.object(pdc, "frappe", fake),
		):
			with self.assertRaises(ValidationError):
				build_pdc_journal_entry_data(doc, WORKFLOW_SENT_TO_BANK, WORKFLOW_CLEARED, POSTING)

	def test_payable_clear_allows_payable_pool_account_type(self) -> None:
		doc = _doc(
			cheque_direction=CHEQUE_DIRECTION_PAYABLE,
			party_type="Supplier",
			party="SUP-1",
			account_paid_from="ACC-POOL-PAY",
			account_paid_to="ACC-AP-DOC",
		)
		settings = dict(_SETTINGS_BASE)
		settings["default_payable_cheque_account"] = "ACC-PAY-POOL-SET"

		def gcv(doctype, name, field, *args, **kwargs):
			if doctype == "Account" and name == "ACC-BANK-GL":
				return {"company": "_TC", "account_type": "Bank"}.get(field)
			if doctype == "Account" and name == "ACC-POOL-PAY":
				return {"account_type": "Payable"}.get(field)
			return None

		fake = self._fake_frappe_for_accounts(gcv)
		with (
			patch.object(pdc, "_get_pdc_settings_for_company", return_value=settings),
			patch.object(pdc, "_pdc_bank_gl_account", return_value="ACC-BANK-GL"),
			patch.object(pdc, "frappe", fake),
		):
			je = build_pdc_journal_entry_data(doc, WORKFLOW_ISSUED, WORKFLOW_CLEARED, POSTING)
		self.assertIsNotNone(je)
		dr = [r for r in je["accounts"] if r.get("debit_in_account_currency")][0]
		cr = [r for r in je["accounts"] if r.get("credit_in_account_currency")][0]
		self.assertEqual(dr["account"], "ACC-POOL-PAY")
		self.assertEqual(dr.get("party"), "SUP-1")
		self.assertEqual(dr.get("party_type"), "Supplier")
		self.assertNotIn("party_type", cr)
		self.assertNotIn("party", cr)
