# Copyright (c) 2026, ERPNext Extensions contributors
"""Unit tests: Class A/B classification, net gate, dimension resolution (3.8.6)."""

from __future__ import annotations

import unittest
from unittest import mock

from erpnext_extensions.iran_accounting.domain.irr_residual_classification import (
	STATUS_BYPASS,
	STATUS_CLASS_B,
	STATUS_PARTNER,
	STATUS_READY,
	classify_amount_rate_residual,
	evaluate_irr_rate_rounding_residual,
)


class TestClassifyAmountRateResidual(unittest.TestCase):
	def test_class_a_amount_authoritative_integer_rate(self):
		# amount=1371, qty=7, rate=ROUND(1371/7)=196 → residual -1
		out = classify_amount_rate_residual(
			qty=7, authoritative_amount=1371, valuation_rate=196, currency="IRR", item_code="X"
		)
		self.assertEqual(out["class"], "A")
		self.assertEqual(out["residual"], -1)

	def test_zero_residual_skip(self):
		out = classify_amount_rate_residual(
			qty=7, authoritative_amount=1372, valuation_rate=196, currency="IRR"
		)
		self.assertEqual(out["class"], "skip")

	def test_class_b_rate_zero_with_amount(self):
		out = classify_amount_rate_residual(
			qty=1, authoritative_amount=4050000000, valuation_rate=0, currency="IRR", item_code="230049"
		)
		self.assertEqual(out["class"], "B")
		self.assertEqual(out["reason"], "valuation_rate_le_zero_with_nonzero_amount")

	def test_class_b_non_integer_rate(self):
		out = classify_amount_rate_residual(
			qty=15,
			authoritative_amount=510000000,
			valuation_rate=32584473.066666666,
			currency="IRR",
		)
		self.assertEqual(out["class"], "B")
		self.assertEqual(out["reason"], "non_integer_rate_under_irr_contract")

	def test_class_b_auth_rate_mismatch(self):
		# integer rate but not ROUND(amount/qty)
		out = classify_amount_rate_residual(
			qty=3,
			authoritative_amount=2244000000,
			valuation_rate=733040000,
			currency="IRR",
		)
		self.assertEqual(out["class"], "B")
		self.assertEqual(out["reason"], "amount_rate_mismatch_not_reproducible_by_approved_pipeline")


class TestEvaluateNetGate(unittest.TestCase):
	def test_non_irr_bypass(self):
		doc = mock.Mock(company="X", doctype="Purchase Receipt", name="PR-1")
		doc.get = lambda k, d=None: getattr(doc, k, d)
		with mock.patch(
			"erpnext_extensions.iran_accounting.domain.irr_residual_classification.is_irr_company",
			return_value=False,
		):
			d = evaluate_irr_rate_rounding_residual(doc)
		self.assertEqual(d.status, STATUS_BYPASS)

	def test_manufacture_excluded_bypass(self):
		doc = mock.Mock(company="C", doctype="Stock Entry", purpose="Manufacture", name="SE-1")
		doc.get = lambda k, d=None: getattr(doc, k, d)
		with mock.patch(
			"erpnext_extensions.iran_accounting.domain.irr_residual_classification.is_irr_company",
			return_value=True,
		):
			d = evaluate_irr_rate_rounding_residual(doc)
		self.assertEqual(d.status, STATUS_BYPASS)
		self.assertIn("manufacture_repack", d.messages[0])

	def test_class_b_pr_shape_fails_before_round_off_lookup(self):
		row = mock.Mock(
			qty=1,
			base_amount=4050000000,
			amount=4050000000,
			valuation_rate=0,
			base_rate=4050000000,
			item_code="230049",
			idx=2,
			name="r1",
			landed_cost_voucher_amount=0,
			department="Dept-A",
		)
		row.get = lambda k, d=None: getattr(row, k, d)
		doc = mock.Mock(
			company="C",
			doctype="Purchase Receipt",
			name="MAT-PRE-TEST",
			items=[row],
			department=None,
		)
		doc.get = lambda k, d=None: getattr(doc, k, d)

		resolve_calls = []

		def resolve(company, require=True):
			resolve_calls.append(company)
			return {"account": "RO", "cost_center": "CC"}

		with (
			mock.patch(
				"erpnext_extensions.iran_accounting.domain.irr_residual_classification.is_irr_company",
				return_value=True,
			),
			mock.patch(
				"erpnext_extensions.iran_accounting.domain.irr_residual_classification.get_company_currency",
				return_value="IRR",
			),
			mock.patch(
				"erpnext_extensions.iran_accounting.domain.irr_rounding_residual.resolve_company_round_off",
				side_effect=resolve,
			),
			mock.patch(
				"erpnext_extensions.iran_accounting.domain.irr_residual_classification._dimension_fieldnames",
				return_value=["department"],
			),
		):
			d = evaluate_irr_rate_rounding_residual(doc, gl_entries=None)

		self.assertEqual(d.status, STATUS_CLASS_B)
		self.assertEqual(resolve_calls, [], "Round Off Account must not be resolved on Class B")

	def test_net_zero_bypass_no_account_lookup(self):
		row = mock.Mock(
			qty=7,
			base_amount=1372,
			amount=1372,
			valuation_rate=196,
			base_rate=196,
			item_code="X",
			idx=1,
			name="r1",
			landed_cost_voucher_amount=0,
			department="D",
		)
		row.get = lambda k, d=None: getattr(row, k, d)
		doc = mock.Mock(
			company="C", doctype="Purchase Receipt", name="PR-OK", items=[row], department="D"
		)
		doc.get = lambda k, d=None: getattr(doc, k, d)
		resolve_calls = []

		with (
			mock.patch(
				"erpnext_extensions.iran_accounting.domain.irr_residual_classification.is_irr_company",
				return_value=True,
			),
			mock.patch(
				"erpnext_extensions.iran_accounting.domain.irr_residual_classification.get_company_currency",
				return_value="IRR",
			),
			mock.patch(
				"erpnext_extensions.iran_accounting.domain.irr_rounding_residual.resolve_company_round_off",
				side_effect=lambda *a, **k: resolve_calls.append(1) or {"account": "RO", "cost_center": "CC"},
			),
			mock.patch(
				"erpnext_extensions.iran_accounting.domain.irr_residual_classification._dimension_fieldnames",
				return_value=["department"],
			),
		):
			d = evaluate_irr_rate_rounding_residual(doc)
		self.assertEqual(d.status, STATUS_BYPASS)
		self.assertEqual(resolve_calls, [])

	def test_no_partner_fails_closed(self):
		class _R:
			def __init__(self, **kw):
				self.__dict__.update(kw)

			def get(self, k, default=None):
				return self.__dict__.get(k, default)

		class _D:
			def __init__(self, **kw):
				self.__dict__.update(kw)

			def get(self, k, default=None):
				return self.__dict__.get(k, default)

			def get_debit_field_precision(self):
				return 0

		row = _R(
			qty=7,
			transfer_qty=7,
			amount=1371,
			valuation_rate=196,
			basic_rate=196,
			basic_amount=1372,
			additional_cost=0,
			landed_cost_voucher_amount=0,
			item_code="X",
			idx=1,
			name="r1",
			t_warehouse="WH-T",
			s_warehouse=None,
			department="D",
		)
		doc = _D(
			company="C",
			doctype="Stock Entry",
			purpose="Material Receipt",
			name="SE-1",
			items=[row],
			department="D",
			additional_costs=[],
		)
		gl = [
			{"account": "Stock - T", "debit": 1371, "credit": 0, "company": "C"},
		]

		with (
			mock.patch(
				"erpnext_extensions.iran_accounting.domain.irr_residual_classification.is_irr_company",
				return_value=True,
			),
			mock.patch(
				"erpnext_extensions.iran_accounting.domain.irr_residual_classification.get_company_currency",
				return_value="IRR",
			),
			mock.patch(
				"erpnext_extensions.iran_accounting.domain.irr_rounding_residual.resolve_company_round_off",
				return_value={"account": "RO - T", "cost_center": "CC-RO"},
			),
			mock.patch(
				"erpnext_extensions.iran_accounting.domain.irr_rounding_residual.validate_round_off_configuration",
				return_value=None,
			),
			mock.patch(
				"erpnext_extensions.iran_accounting.domain.irr_residual_classification.resolve_round_off_dimensions",
				return_value={"department": "D"},
			),
			mock.patch(
				"erpnext_extensions.iran_accounting.domain.irr_residual_classification._dimension_fieldnames",
				return_value=["department"],
			),
			mock.patch(
				"erpnext_extensions.iran_accounting.zero_value_transfer._should_force_balanced_transfer_gl",
				return_value=False,
			),
			mock.patch(
				"erpnext_extensions.iran_accounting.domain.irr_rounding_residual._is_stock_account",
				side_effect=lambda a: a == "Stock - T",
			),
			mock.patch(
				"erpnext_extensions.iran_accounting.domain.irr_rounding_residual._is_stock_adjustment_account",
				return_value=False,
			),
		):
			d = evaluate_irr_rate_rounding_residual(doc, gl_entries=gl)

		self.assertEqual(d.status, STATUS_PARTNER)
		self.assertTrue(d.class_a_rows)
		self.assertEqual(d.net_signed_debit, 1.0)


if __name__ == "__main__":
	unittest.main()
