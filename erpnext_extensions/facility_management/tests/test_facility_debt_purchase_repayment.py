# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

"""Unit tests for Facility Repayment credit-source branch (Debt Purchase vs Bank)."""

from __future__ import annotations

import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from erpnext_extensions.facility_management.facility_debt_purchase import (
	REPAYMENT_METHOD_BANK,
	REPAYMENT_METHOD_DEBT_PURCHASE,
)


class TestRepaymentCreditSourceBranch(unittest.TestCase):
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
		base = dict(
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
			get=lambda k, d=None: getattr(base_ns, k, d),
		)
		# rebuild with SimpleNamespace after defining get carefully
		ns = SimpleNamespace(**{k: v for k, v in base.items() if k != "get"})

		def _get(key, default=None):
			return getattr(ns, key, default)

		ns.get = _get
		return ns

	def test_bank_method_credits_bank(self):
		from erpnext_extensions.facility_management.facility_accounting import build_repayment_je_plan

		facility = self._facility()
		repayment = self._repayment(REPAYMENT_METHOD_BANK, bank_account="BANK")
		pdc = SimpleNamespace(
			name="PDC-1",
			cheque_direction="Receivable",
			workflow_state="Assigned to Bank for Debt Purchase",
			company="C",
			currency="IRR",
			cheque_amount=1000,
			debt_purchase_repayment=None,
		)
		with (
			patch(
				"erpnext_extensions.facility_management.facility_accounting.frappe.get_doc",
				side_effect=lambda *a, **k: facility if a and a[0] == "Facility" else pdc,
			),
			patch(
				"erpnext_extensions.facility_management.facility_accounting.get_facility_settings_doc",
				return_value=None,
			),
			patch(
				"erpnext_extensions.facility_management.facility_accounting.validate_repayment_je_prerequisites",
			),
			patch(
				"erpnext_extensions.facility_management.facility_accounting._repayment_amounts",
				return_value=(Decimal("900"), Decimal("100"), Decimal("0")),
			),
			patch(
				"erpnext_extensions.facility_management.facility_accounting.resolve_account",
				side_effect=lambda fieldname, **kw: {
					"bank_account": "BANK",
					"loan_payable_account": "LOAN",
					"deferred_loan_interest_account": "DEF",
					"interest_expense_account": "IEXP",
					"penalty_expense_account": "PEN",
				}.get(fieldname),
			),
			patch(
				"erpnext_extensions.facility_management.facility_accounting.repayment_je_row_dimensions",
				return_value={},
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
		credit = [r for r in plan if not r["debit"]]
		self.assertTrue(any(r["role"] == "bank" and r["account"] == "BANK" for r in credit))
		self.assertFalse(any(r["role"] == "debt_purchase_in_collection" for r in plan))

	def test_debt_purchase_method_credits_dpic(self):
		from erpnext_extensions.facility_management.facility_accounting import build_repayment_je_plan

		facility = self._facility()
		repayment = self._repayment(
			REPAYMENT_METHOD_DEBT_PURCHASE, post_dated_cheque="PDC-1", bank_account=None
		)
		pdc = SimpleNamespace(
			name="PDC-1",
			cheque_direction="Receivable",
			workflow_state="Assigned to Bank for Debt Purchase",
			company="C",
			currency="IRR",
			cheque_amount=1000,
			debt_purchase_repayment=None,
		)
		with (
			patch(
				"erpnext_extensions.facility_management.facility_debt_purchase.validate_debt_purchase_cheque_repayment",
				return_value={"pdc": pdc, "dpic_account": "DPIC", "principal": Decimal("900"), "profit": Decimal("100")},
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
				}.get(fieldname),
			),
			patch(
				"erpnext_extensions.facility_management.facility_accounting.repayment_je_row_dimensions",
				return_value={},
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
		settlement = [r for r in plan if r["role"] == "debt_purchase_in_collection"]
		self.assertEqual(len(settlement), 1)
		self.assertFalse(settlement[0]["debit"])
		self.assertEqual(settlement[0]["account"], "DPIC")
		self.assertEqual(settlement[0]["amount"], Decimal("1000"))
		self.assertFalse(any(r["role"] == "bank" for r in plan))
		# deferred + interest expense still present
		self.assertTrue(any(r["role"] == "deferred_credit" for r in plan))
		self.assertTrue(any(r["role"] == "interest_expense" for r in plan))


if __name__ == "__main__":
	unittest.main()
