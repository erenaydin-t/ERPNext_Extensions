# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

"""Unit tests for Debt Purchase workflow edges and JE builders (no DB)."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from erpnext_extensions.cheque_management.pdc_transition_accounting_registry import (
	get_accounting_transition_spec,
)
from erpnext_extensions.cheque_management.pdc_workflow_state_machine import (
	CHEQUE_DIRECTION_PAYABLE,
	CHEQUE_DIRECTION_RECEIVABLE,
	PDC_ACCOUNTING_JOURNAL_ENTRY,
	PDC_ACCOUNTING_NO_DOCUMENT,
	PDC_VALIDATION_DEBT_PURCHASE_ASSIGNED_NO_CLEAR,
	PDC_VALIDATION_DEBT_PURCHASE_SETTLED_FACILITY_ONLY,
	PDC_VALIDATION_DEBT_PURCHASE_SETTLED_IS_TERMINAL,
	WORKFLOW_ASSIGNED_DEBT_PURCHASE,
	WORKFLOW_CLEARED,
	WORKFLOW_DEBT_PURCHASE_SETTLED,
	WORKFLOW_DRAFT,
	WORKFLOW_REGISTERED,
	WORKFLOW_RETURNED,
	WORKFLOW_SENT_TO_BANK,
	get_pdc_accounting_decision,
	get_pdc_workflow_transition_validation_error,
)
from erpnext_extensions.cheque_management.pdc_workflow_to_cheque_status import (
	CHEQUE_STATUS_DEBT_PURCHASE_IN_COLLECTION,
	CHEQUE_STATUS_DEBT_PURCHASE_SETTLED,
	map_workflow_state_to_cheque_status,
)
from erpnext_extensions.facility_management.facility_debt_purchase import (
	REPAYMENT_METHOD_BANK,
	REPAYMENT_METHOD_DEBT_PURCHASE,
	normalize_repayment_method,
)


def _err(direction, prev, new):
	return get_pdc_workflow_transition_validation_error(direction, prev, new)


class TestDebtPurchaseWorkflow(unittest.TestCase):
	def test_registered_to_assigned_allowed(self):
		self.assertIsNone(
			_err(CHEQUE_DIRECTION_RECEIVABLE, WORKFLOW_REGISTERED, WORKFLOW_ASSIGNED_DEBT_PURCHASE)
		)

	def test_assigned_to_returned_allowed(self):
		self.assertIsNone(
			_err(CHEQUE_DIRECTION_RECEIVABLE, WORKFLOW_ASSIGNED_DEBT_PURCHASE, WORKFLOW_RETURNED)
		)

	def test_assigned_to_cleared_forbidden(self):
		self.assertEqual(
			_err(CHEQUE_DIRECTION_RECEIVABLE, WORKFLOW_ASSIGNED_DEBT_PURCHASE, WORKFLOW_CLEARED),
			PDC_VALIDATION_DEBT_PURCHASE_ASSIGNED_NO_CLEAR,
		)

	def test_assigned_to_settled_facility_only(self):
		self.assertEqual(
			_err(
				CHEQUE_DIRECTION_RECEIVABLE,
				WORKFLOW_ASSIGNED_DEBT_PURCHASE,
				WORKFLOW_DEBT_PURCHASE_SETTLED,
			),
			PDC_VALIDATION_DEBT_PURCHASE_SETTLED_FACILITY_ONLY,
		)

	def test_settled_is_terminal(self):
		self.assertEqual(
			_err(CHEQUE_DIRECTION_RECEIVABLE, WORKFLOW_DEBT_PURCHASE_SETTLED, WORKFLOW_ASSIGNED_DEBT_PURCHASE),
			PDC_VALIDATION_DEBT_PURCHASE_SETTLED_IS_TERMINAL,
		)

	def test_payable_cannot_assign(self):
		self.assertIsNotNone(
			_err(CHEQUE_DIRECTION_PAYABLE, WORKFLOW_REGISTERED, WORKFLOW_ASSIGNED_DEBT_PURCHASE)
		)

	def test_accounting_decisions(self):
		self.assertEqual(
			get_pdc_accounting_decision(
				CHEQUE_DIRECTION_RECEIVABLE, WORKFLOW_REGISTERED, WORKFLOW_ASSIGNED_DEBT_PURCHASE
			),
			PDC_ACCOUNTING_JOURNAL_ENTRY,
		)
		self.assertEqual(
			get_pdc_accounting_decision(
				CHEQUE_DIRECTION_RECEIVABLE, WORKFLOW_ASSIGNED_DEBT_PURCHASE, WORKFLOW_RETURNED
			),
			PDC_ACCOUNTING_JOURNAL_ENTRY,
		)
		self.assertEqual(
			get_pdc_accounting_decision(
				CHEQUE_DIRECTION_RECEIVABLE,
				WORKFLOW_ASSIGNED_DEBT_PURCHASE,
				WORKFLOW_DEBT_PURCHASE_SETTLED,
			),
			PDC_ACCOUNTING_NO_DOCUMENT,
		)

	def test_cheque_status_mapping(self):
		self.assertEqual(
			map_workflow_state_to_cheque_status(
				CHEQUE_DIRECTION_RECEIVABLE, WORKFLOW_ASSIGNED_DEBT_PURCHASE
			),
			CHEQUE_STATUS_DEBT_PURCHASE_IN_COLLECTION,
		)
		self.assertEqual(
			map_workflow_state_to_cheque_status(
				CHEQUE_DIRECTION_RECEIVABLE, WORKFLOW_DEBT_PURCHASE_SETTLED
			),
			CHEQUE_STATUS_DEBT_PURCHASE_SETTLED,
		)

	def test_registry_specs(self):
		spec = get_accounting_transition_spec(
			CHEQUE_DIRECTION_RECEIVABLE, WORKFLOW_REGISTERED, WORKFLOW_ASSIGNED_DEBT_PURCHASE
		)
		self.assertIsNotNone(spec)
		self.assertFalse(spec.touches_party)
		spec2 = get_accounting_transition_spec(
			CHEQUE_DIRECTION_RECEIVABLE, WORKFLOW_ASSIGNED_DEBT_PURCHASE, WORKFLOW_RETURNED
		)
		self.assertTrue(spec2.touches_party)

	def test_repayment_method_legacy_default(self):
		self.assertEqual(normalize_repayment_method(None), REPAYMENT_METHOD_BANK)
		self.assertEqual(normalize_repayment_method(""), REPAYMENT_METHOD_BANK)
		self.assertEqual(normalize_repayment_method(REPAYMENT_METHOD_DEBT_PURCHASE), REPAYMENT_METHOD_DEBT_PURCHASE)


class TestDebtPurchaseJeBuilder(unittest.TestCase):
	def test_assign_builder_roles(self):
		from erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque import (
			build_pdc_journal_entry_data,
		)

		doc = SimpleNamespace(
			cheque_direction=CHEQUE_DIRECTION_RECEIVABLE,
			cheque_amount=1000,
			cheque_no="DP-1",
			cheque_purpose=None,
			party_type="Customer",
			party="CUST-1",
			company="C",
			account_paid_to=None,
			account_paid_from=None,
			name="PDC-DP-1",
			bank_account=None,
			workflow_state=WORKFLOW_REGISTERED,
			cheque_status="In Hand",
			cheque_due_date=None,
		)
		acc = {
			"cheques_in_hand": "CIH",
			"debt_purchase_in_collection": "DPIC",
			"cheques_in_clearing": None,
			"payable_cheque": None,
			"protested": None,
			"endorsement_account": None,
		}
		with (
			patch(
				"erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque.resolve_pdc_accounts_for_journal",
				return_value=acc,
			),
			patch(
				"erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque._get_pdc_settings_for_company",
				return_value=None,
			),
			patch(
				"erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque._pdc_bank_gl_account",
				return_value=None,
			),
		):
			payload = build_pdc_journal_entry_data(
				doc, WORKFLOW_REGISTERED, WORKFLOW_ASSIGNED_DEBT_PURCHASE
			)
		self.assertIsNotNone(payload)
		accounts = payload["accounts"]
		self.assertEqual(accounts[0]["account"], "DPIC")
		self.assertEqual(accounts[0]["debit_in_account_currency"], 1000)
		self.assertEqual(accounts[1]["account"], "CIH")
		self.assertEqual(accounts[1]["credit_in_account_currency"], 1000)

	def test_return_from_assigned_credits_dpic(self):
		from erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque import (
			build_pdc_journal_entry_data,
		)

		doc = SimpleNamespace(
			cheque_direction=CHEQUE_DIRECTION_RECEIVABLE,
			cheque_amount=1000,
			cheque_no="DP-1",
			cheque_purpose=None,
			party_type="Customer",
			party="CUST-1",
			company="C",
			account_paid_to=None,
			account_paid_from="AR",
			name="PDC-DP-1",
			bank_account=None,
			workflow_state=WORKFLOW_ASSIGNED_DEBT_PURCHASE,
			cheque_status="Debt Purchase In Collection",
			cheque_due_date=None,
		)
		acc = {
			"cheques_in_hand": "CIH",
			"debt_purchase_in_collection": "DPIC",
			"cheques_in_clearing": None,
			"payable_cheque": None,
			"protested": None,
			"endorsement_account": None,
		}
		with (
			patch(
				"erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque.resolve_pdc_accounts_for_journal",
				return_value=acc,
			),
			patch(
				"erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque._get_pdc_settings_for_company",
				return_value=None,
			),
			patch(
				"erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque._pdc_bank_gl_account",
				return_value=None,
			),
			patch(
				"erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque.receivable_sales_invoice_settlement_slices",
				return_value=[],
			),
			patch(
				"erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque._get_party_account_or_company_default",
				return_value="AR",
			),
		):
			payload = build_pdc_journal_entry_data(
				doc, WORKFLOW_ASSIGNED_DEBT_PURCHASE, WORKFLOW_RETURNED
			)
		self.assertIsNotNone(payload)
		accounts = payload["accounts"]
		self.assertEqual(accounts[0]["account"], "AR")
		self.assertEqual(accounts[0]["debit_in_account_currency"], 1000)
		self.assertEqual(accounts[1]["account"], "DPIC")
		self.assertEqual(accounts[1]["credit_in_account_currency"], 1000)

	def test_assign_missing_dpic_returns_none(self):
		from erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque import (
			build_pdc_journal_entry_data,
		)

		doc = SimpleNamespace(
			cheque_direction=CHEQUE_DIRECTION_RECEIVABLE,
			cheque_amount=1000,
			cheque_no="DP-1",
			cheque_purpose=None,
			party_type="Customer",
			party="CUST-1",
			company="C",
			account_paid_to="CIH",
			account_paid_from=None,
			name="PDC-DP-2",
			bank_account=None,
			workflow_state=WORKFLOW_REGISTERED,
			cheque_status="In Hand",
			cheque_due_date=None,
		)
		acc = {
			"cheques_in_hand": "CIH",
			"debt_purchase_in_collection": None,
			"cheques_in_clearing": None,
			"payable_cheque": None,
			"protested": None,
			"endorsement_account": None,
		}
		with (
			patch(
				"erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque.resolve_pdc_accounts_for_journal",
				return_value=acc,
			),
			patch(
				"erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque._get_pdc_settings_for_company",
				return_value=None,
			),
		):
			payload = build_pdc_journal_entry_data(
				doc, WORKFLOW_REGISTERED, WORKFLOW_ASSIGNED_DEBT_PURCHASE
			)
			self.assertIsNone(payload)


if __name__ == "__main__":
	unittest.main()
