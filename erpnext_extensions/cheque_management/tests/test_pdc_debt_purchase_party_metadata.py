# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

"""Row-level Party / reference metadata tests for Debt Purchase JE builders.

Acceptance: DP Assignment has no Party on either pool row; DP Bounce has no Party
on Protested debit / DPIC credit; Facility DP settlement credit matches bank
credit metadata shape (no Party). Existing Sent-to-Bank / Registered→Returned
behavior must remain unchanged.
"""

from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque as pdc_mod
from erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque import (
	build_pdc_journal_entry_data,
)
from erpnext_extensions.cheque_management.pdc_workflow_state_machine import (
	CHEQUE_DIRECTION_RECEIVABLE,
	WORKFLOW_ASSIGNED_DEBT_PURCHASE,
	WORKFLOW_BOUNCED,
	WORKFLOW_REGISTERED,
	WORKFLOW_RETURNED,
	WORKFLOW_SENT_TO_BANK,
)
from erpnext_extensions.facility_management.facility_debt_purchase import (
	REPAYMENT_METHOD_BANK,
	REPAYMENT_METHOD_DEBT_PURCHASE,
)

POSTING = date(2026, 7, 26)

_SETTINGS = {
	"default_cheques_in_hand_account": "ACC-CIH",
	"default_cheques_in_clearing_account": "ACC-CLR",
	"default_payable_cheque_account": "ACC-POOL",
	"default_protested_account": "ACC-PROT",
	"default_endorsement_account": "ACC-ENDORSE",
	"default_debt_purchase_in_collection_account": "ACC-DPIC",
}


def _doc(**overrides):
	base = dict(
		company="_TC",
		cheque_direction=CHEQUE_DIRECTION_RECEIVABLE,
		party_type="Customer",
		party="CUST-1",
		cheque_amount=1000.0,
		cheque_no="DP-META-1",
		cheque_purpose=None,
		account_paid_to="ACC-CIH",
		account_paid_from="ACC-AR",
		bank_account="BA-1",
		name="PDC-META-1",
		workflow_state=WORKFLOW_REGISTERED,
		cheque_status="In Hand",
		cheque_due_date=None,
		holder_party_type=None,
		holder_party=None,
		allocation_mode="direct_settlement",
	)
	base.update(overrides)
	return SimpleNamespace(**base)


def _has_party(row) -> bool:
	return bool(row.get("party_type") or row.get("party"))


def _has_invoice_ref(row) -> bool:
	return bool(row.get("reference_type") or row.get("reference_name"))


class TestDebtPurchaseAssignmentPartyMetadata(unittest.TestCase):
	def test_assignment_two_rows_no_party_no_invoice_refs(self) -> None:
		doc = _doc()
		with (
			patch.object(pdc_mod, "_get_pdc_settings_for_company", return_value=dict(_SETTINGS)),
			patch.object(pdc_mod, "_get_party_account_or_company_default", return_value="ACC-AR"),
			patch.object(pdc_mod, "_pdc_bank_gl_account", return_value="ACC-BANK"),
			patch.object(pdc_mod, "frappe") as mf,
		):
			mf._ = lambda s: s
			je = build_pdc_journal_entry_data(
				doc, WORKFLOW_REGISTERED, WORKFLOW_ASSIGNED_DEBT_PURCHASE, POSTING
			)
		self.assertIsNotNone(je)
		rows = je["accounts"]
		self.assertEqual(len(rows), 2)
		self.assertEqual(rows[0]["account"], "ACC-DPIC")
		self.assertEqual(rows[0]["debit_in_account_currency"], 1000.0)
		self.assertEqual(rows[1]["account"], "ACC-CIH")
		self.assertEqual(rows[1]["credit_in_account_currency"], 1000.0)
		for r in rows:
			self.assertFalse(_has_party(r), r)
			self.assertFalse(_has_invoice_ref(r), r)

	def test_assignment_builder_shape_matches_sent_to_bank_without_party(self) -> None:
		"""Both Sent to Bank and DP Assignment keep pool-only rows (no Party)."""
		doc = _doc()
		with (
			patch.object(pdc_mod, "_get_pdc_settings_for_company", return_value=dict(_SETTINGS)),
			patch.object(pdc_mod, "_get_party_account_or_company_default", return_value="ACC-AR"),
			patch.object(pdc_mod, "_pdc_bank_gl_account", return_value="ACC-BANK"),
			patch.object(pdc_mod, "frappe") as mf,
		):
			mf._ = lambda s: s
			stb = build_pdc_journal_entry_data(doc, WORKFLOW_REGISTERED, WORKFLOW_SENT_TO_BANK, POSTING)
			dp = build_pdc_journal_entry_data(
				doc, WORKFLOW_REGISTERED, WORKFLOW_ASSIGNED_DEBT_PURCHASE, POSTING
			)
		self.assertTrue(all(not _has_party(r) for r in stb["accounts"]))
		self.assertTrue(all(not _has_party(r) for r in dp["accounts"]))
		self.assertEqual(len(stb["accounts"]), 2)
		self.assertEqual(len(dp["accounts"]), 2)


class TestDebtPurchaseBouncePartyMetadata(unittest.TestCase):
	def test_bounce_debits_protested_credits_dpic_no_party(self) -> None:
		doc = _doc(workflow_state=WORKFLOW_ASSIGNED_DEBT_PURCHASE)
		with (
			patch.object(pdc_mod, "_get_pdc_settings_for_company", return_value=dict(_SETTINGS)),
			patch.object(pdc_mod, "_get_party_account_or_company_default", return_value="ACC-AR"),
			patch.object(pdc_mod, "_pdc_bank_gl_account", return_value="ACC-BANK"),
			patch.object(pdc_mod, "frappe") as mf,
		):
			mf._ = lambda s: s
			je = build_pdc_journal_entry_data(
				doc, WORKFLOW_ASSIGNED_DEBT_PURCHASE, WORKFLOW_BOUNCED, POSTING
			)
		self.assertIsNotNone(je)
		dr, cr = je["accounts"]
		self.assertEqual(dr["account"], "ACC-PROT")
		self.assertEqual(dr["debit_in_account_currency"], 1000.0)
		self.assertFalse(_has_party(dr), dr)
		self.assertFalse(_has_invoice_ref(dr), dr)
		self.assertEqual(cr["account"], "ACC-DPIC")
		self.assertEqual(cr["credit_in_account_currency"], 1000.0)
		self.assertFalse(_has_party(cr), cr)
		self.assertFalse(_has_invoice_ref(cr), cr)
		self.assertNotEqual(dr["account"], "ACC-CIH")

	def test_bounce_does_not_use_cih_unlike_assignment_credit(self) -> None:
		"""Assign credits CIH; Bounce debits Protested (not reverse into CIH)."""
		doc = _doc()
		with (
			patch.object(pdc_mod, "_get_pdc_settings_for_company", return_value=dict(_SETTINGS)),
			patch.object(pdc_mod, "_get_party_account_or_company_default", return_value="ACC-AR"),
			patch.object(pdc_mod, "_pdc_bank_gl_account", return_value="ACC-BANK"),
			patch.object(pdc_mod, "frappe") as mf,
		):
			mf._ = lambda s: s
			assign = build_pdc_journal_entry_data(
				doc, WORKFLOW_REGISTERED, WORKFLOW_ASSIGNED_DEBT_PURCHASE, POSTING
			)
			doc.workflow_state = WORKFLOW_ASSIGNED_DEBT_PURCHASE
			bounce = build_pdc_journal_entry_data(
				doc, WORKFLOW_ASSIGNED_DEBT_PURCHASE, WORKFLOW_BOUNCED, POSTING
			)
		self.assertEqual(assign["accounts"][0]["account"], "ACC-DPIC")
		self.assertEqual(assign["accounts"][1]["account"], "ACC-CIH")
		self.assertEqual(bounce["accounts"][0]["account"], "ACC-PROT")
		self.assertEqual(bounce["accounts"][1]["account"], "ACC-DPIC")
		self.assertTrue(all(not _has_party(r) for r in assign["accounts"]))
		self.assertTrue(all(not _has_party(r) for r in bounce["accounts"]))


class TestDebtPurchaseFacilitySettlementMetadata(unittest.TestCase):
	def _facility(self):
		return SimpleNamespace(
			name="FAC-1",
			company="C",
			facility_type="FT-DP",
			facility_name="F",
			bank=None,
			contract_date="2026-01-01",
			receive_date=None,
			principal_amount=10000,
			profit_amount=1000,
			total_liability_amount=11000,
			installment_count=12,
		)

	def _repayment(self, method, **extra):
		ns = SimpleNamespace(
			name="FREP-1",
			facility="FAC-1",
			company="C",
			posting_date="2026-07-01",
			principal_amount=900,
			profit_amount=100,
			penalty_amount=0,
			repayment_method=method,
			post_dated_cheque=extra.get("post_dated_cheque"),
			bank_account=extra.get("bank_account", "BANK"),
			loan_payable_account="LOAN",
			deferred_loan_interest_account="DEF",
			interest_expense_account="IEXP",
			penalty_expense_account="PEN",
			repayment_remarks_template=None,
		)

		def _get(key, default=None):
			return getattr(ns, key, default)

		ns.get = _get
		return ns

	def test_dp_settlement_credit_has_no_party_and_matches_bank_dims_role(self) -> None:
		from erpnext_extensions.facility_management.facility_accounting import build_repayment_je_plan

		facility = self._facility()
		repayment = self._repayment(
			REPAYMENT_METHOD_DEBT_PURCHASE, post_dated_cheque="PDC-1", bank_account=None
		)
		pdc = SimpleNamespace(
			name="PDC-1",
			cheque_direction="Receivable",
			workflow_state=WORKFLOW_ASSIGNED_DEBT_PURCHASE,
			company="C",
			currency="IRR",
			cheque_amount=1000,
			debt_purchase_repayment=None,
			party_type="Customer",
			party="CUST-FROM-PDC",
		)
		with (
			patch(
				"erpnext_extensions.facility_management.facility_debt_purchase.validate_debt_purchase_cheque_repayment",
				return_value={
					"pdc": pdc,
					"dpic_account": "DPIC",
					"principal": Decimal("900"),
					"profit": Decimal("100"),
				},
			),
			patch(
				"erpnext_extensions.facility_management.facility_accounting.validate_repayment_je_prerequisites",
			),
			patch(
				"erpnext_extensions.facility_management.facility_accounting.get_facility_settings_doc",
				return_value=None,
			),
			patch(
				"erpnext_extensions.facility_management.facility_accounting._repayment_amounts",
				return_value=(Decimal("900"), Decimal("100"), Decimal("0")),
			),
			patch(
				"erpnext_extensions.facility_management.facility_accounting.resolve_account",
				side_effect=lambda fieldname, **kw: {
					"loan_payable_account": "LOAN",
					"deferred_loan_interest_account": "DEF",
					"interest_expense_account": "IEXP",
					"penalty_expense_account": "PEN",
					"bank_account": "BANK",
				}.get(fieldname),
			),
			patch(
				"erpnext_extensions.facility_management.facility_accounting.repayment_je_row_dimensions",
				side_effect=lambda role, *a, **k: {"bank_dimension": "BD-1"} if role == "bank" else {},
			),
			patch(
				"erpnext_extensions.facility_management.facility_accounting.render_facility_template",
				side_effect=lambda t, c: t or "",
			),
			patch(
				"erpnext_extensions.facility_management.facility_accounting.build_template_context",
				return_value={},
			),
			patch(
				"erpnext_extensions.facility_management.facility_accounting._repayment_row_templates",
				return_value={
					"remark": "r",
					"bank": "b",
					"principal": "p",
					"profit": "pr",
					"penalty": "pe",
				},
			),
		):
			plan = build_repayment_je_plan(repayment, facility=facility)
			bank_rep = self._repayment(REPAYMENT_METHOD_BANK, bank_account="BANK")
			bank_plan = build_repayment_je_plan(bank_rep, facility=facility)

		dp_credit = next(r for r in plan if r["role"] == "debt_purchase_in_collection")
		bank_credit = next(r for r in bank_plan if r["role"] == "bank")
		self.assertFalse(dp_credit["debit"])
		self.assertEqual(dp_credit["account"], "DPIC")
		self.assertEqual(dp_credit["amount"], Decimal("1000"))
		# Same dimension shape as bank credit (bank_dimension via bank dim-role).
		self.assertEqual(dp_credit.get("dims"), bank_credit.get("dims"))
		# No PDC customer propagated onto any Facility plan row.
		for r in plan:
			self.assertNotIn("party", r)
			self.assertNotIn("party_type", r)
			self.assertNotIn("reference_type", r)
			self.assertNotIn("reference_name", r)

		# Common debit / deferred legs match bank repayment (roles + amounts).
		def _by_role(p):
			return {r["role"]: r for r in p if r["role"] != "bank" and r["role"] != "debt_purchase_in_collection"}

		dp_common = _by_role(plan)
		bank_common = _by_role(bank_plan)
		self.assertEqual(set(dp_common), set(bank_common))
		for role in dp_common:
			self.assertEqual(dp_common[role]["account"], bank_common[role]["account"])
			self.assertEqual(dp_common[role]["amount"], bank_common[role]["amount"])
			self.assertEqual(dp_common[role]["debit"], bank_common[role]["debit"])


class TestExistingPartyPolicyRegression(unittest.TestCase):
	def test_sent_to_bank_has_no_party_on_either_row(self) -> None:
		doc = _doc()
		with (
			patch.object(pdc_mod, "_get_pdc_settings_for_company", return_value=dict(_SETTINGS)),
			patch.object(pdc_mod, "_get_party_account_or_company_default", return_value="ACC-AR"),
			patch.object(pdc_mod, "_pdc_bank_gl_account", return_value="ACC-BANK"),
			patch.object(pdc_mod, "frappe") as mf,
		):
			mf._ = lambda s: s
			je = build_pdc_journal_entry_data(doc, WORKFLOW_REGISTERED, WORKFLOW_SENT_TO_BANK, POSTING)
		for r in je["accounts"]:
			self.assertFalse(_has_party(r), r)

	def test_registered_returned_party_only_on_ar_not_cih(self) -> None:
		doc = _doc()
		with (
			patch.object(pdc_mod, "_get_pdc_settings_for_company", return_value=dict(_SETTINGS)),
			patch.object(pdc_mod, "_get_party_account_or_company_default", return_value="ACC-AR"),
			patch.object(pdc_mod, "_pdc_bank_gl_account", return_value="ACC-BANK"),
			patch.object(pdc_mod, "receivable_sales_invoice_settlement_slices", return_value=[]),
			patch.object(pdc_mod, "frappe") as mf,
		):
			mf._ = lambda s: s
			je = build_pdc_journal_entry_data(doc, WORKFLOW_REGISTERED, WORKFLOW_RETURNED, POSTING)
		dr, cr = je["accounts"]
		self.assertEqual(dr.get("party"), "CUST-1")
		self.assertEqual(cr["account"], "ACC-CIH")
		self.assertFalse(_has_party(cr), cr)


if __name__ == "__main__":
	unittest.main()
